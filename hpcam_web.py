#!/usr/bin/env python3
"""Controller + localhost web server for the HP USB Webcam tuner UI (ui/).

Serves the page, a MJPEG preview, a server-sent-events status feed and a small JSON API.
Bound to 127.0.0.1 only; every API call and stream needs the per-run token embedded in the page,
so other web pages open in a browser cannot drive the camera.
"""
import json, os, secrets, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hpcam  # noqa: E402

UI_DIR = os.path.join(HERE, 'ui')
SW, SH = 80, 60                       # stats frame size
PW, PH = 640, 480
SERVICE = os.path.expanduser('~/.config/systemd/user/hpcam.service')


def photo_dir():
    try:
        out = subprocess.run(['xdg-user-dir', 'PICTURES'], capture_output=True, text=True).stdout.strip()
    except OSError:
        out = ''
    return os.path.join(out or os.path.expanduser('~/Pictures'), 'HP Webcam')


def loopback_device():
    import glob
    for d in sorted(glob.glob('/sys/class/video4linux/video*')):
        try:
            name = open(d + '/name').read().strip()
        except OSError:
            continue
        if 'Dummy' in name or 'Loopback' in name or 'tuned' in name:
            return '/dev/' + os.path.basename(d), name
    return None, None


class Capture:
    """One ffmpeg process: MJPEG preview on stdout, small RGB stats frames on a second pipe,
    and optionally a processed copy into a v4l2loopback device."""

    def __init__(self, on_stats):
        self.proc = None
        self.on_stats = on_stats
        self.jpeg = None
        self.jseq = 0
        self.cond = threading.Condition()
        self.error = ''

    def start(self, dev, loopback=None, denoise=0.0, sharpen=0.0):
        self.stop()
        chain = []
        if loopback and denoise > 0:
            chain.append('hqdn3d=%.2f:%.2f:%.2f:%.2f' % (denoise, denoise * .75, denoise * 1.5, denoise * 1.5))
        if loopback and sharpen > 0:
            chain.append('unsharp=5:5:%.2f' % sharpen)
        pre = (','.join(chain) + ',') if chain else ''
        r, w = os.pipe()
        # Low latency: no input buffering, single-threaded decode (frame threading holds frames
        # back, and at the camera's ~5 fps in dim light every held frame is ~200 ms of lag).
        cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error',
               '-fflags', 'nobuffer', '-flags', 'low_delay', '-threads', '1',
               '-f', 'v4l2', '-input_format', 'mjpeg',
               '-video_size', '%dx%d' % (PW, PH), '-framerate', '30', '-i', dev]
        stats = '[s]fps=6,scale=%d:%d,format=rgb24[st]' % (SW, SH)
        if loopback:
            # virtual camera on: the preview shows the processed picture (what call apps get)
            graph = '[0:v]%ssplit=3[p][s][v];[p]null[pv];%s;[v]format=yuyv422[lo]' % (pre, stats)
            cmd += ['-filter_complex', graph,
                    '-map', '[pv]', '-fps_mode', 'passthrough', '-c:v', 'mjpeg', '-q:v', '4',
                    '-f', 'mjpeg', 'pipe:1',
                    '-map', '[st]', '-f', 'rawvideo', 'pipe:%d' % w,
                    '-map', '[lo]', '-f', 'v4l2', loopback]
        else:
            # preview = the camera's own JPEGs, copied untouched (no decode, no re-encode);
            # only the small statistics stream is decoded
            cmd += ['-map', '0:v', '-c:v', 'copy', '-fps_mode', 'passthrough', '-f', 'mjpeg', 'pipe:1',
                    '-filter_complex', '[0:v]null[s];' + stats,
                    '-map', '[st]', '-f', 'rawvideo', 'pipe:%d' % w]
        self.error = ''
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(w,))
        os.close(w)
        proc = self.proc
        threading.Thread(target=self._read_jpeg, args=(proc,), daemon=True).start()
        threading.Thread(target=self._read_stats, args=(proc, r), daemon=True).start()
        threading.Thread(target=self._read_err, args=(proc,), daemon=True).start()

    def _read_jpeg(self, proc):
        buf = b''
        while True:
            chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, 'read1') else proc.stdout.read(65536)
            if not chunk:
                break
            buf += chunk
            while True:
                s = buf.find(b'\xff\xd8')
                e = buf.find(b'\xff\xd9', s + 2)
                if s < 0 or e < 0:
                    break
                frame, buf = buf[s:e + 2], buf[e + 2:]
                with self.cond:
                    self.jpeg = frame
                    self.jseq += 1
                    self.cond.notify_all()

    def _read_stats(self, proc, fd):
        n = SW * SH * 3
        with os.fdopen(fd, 'rb') as f:
            while True:
                b = f.read(n)
                if len(b) < n:
                    break
                self.on_stats(np.frombuffer(b, np.uint8).reshape(SH, SW, 3))

    def _read_err(self, proc):
        err = proc.stderr.read().decode(errors='replace').strip()
        if proc is self.proc and err:
            self.error = err.splitlines()[-1]

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc:
            p, self.proc = self.proc, None
            p.terminate()
            try:
                p.wait(2)
            except subprocess.TimeoutExpired:
                p.kill()
        with self.cond:
            self.jpeg = None
            self.cond.notify_all()


class Controller:
    def __init__(self):
        self.lock = threading.RLock()
        self.profile = hpcam.load_profile()
        self.profile.setdefault('virtual', {'denoise': 3.0, 'sharpen': 0.5})
        self.profile.setdefault('awb', False)
        self.cam = None
        self.preview_on = True
        self.virtual_on = False
        self.capture = Capture(self.on_stats)
        self.stats = {'fps': 0.0, 'luma': 0.0, 'rg': 1.0, 'bg': 1.0, 'hist': None}
        self.events = []          # (seq, text) toasts for the UI
        self.ev_seq = 0
        self.last_awb = 0.0
        self.balance_left = 0
        self.save_timer = None
        self.btn_was = False
        self._fps_t, self._fps_n, self._last_jseq = time.time(), 0, 0
        threading.Thread(target=self._housekeeping, daemon=True).start()
        threading.Thread(target=self._button_loop, daemon=True).start()

    # ----- helpers -----
    def toast(self, text):
        with self.lock:
            self.ev_seq += 1
            self.events = (self.events + [(self.ev_seq, text)])[-10:]

    def _cam_do(self, fn):
        with self.lock:
            if not self.cam:
                return None
            try:
                return fn(self.cam)
            except OSError:
                self._drop_cam()
                return None

    def _drop_cam(self):
        try:
            self.cam.close()
        except Exception:
            pass
        self.cam = None
        self.capture.stop()

    def _schedule_save(self):
        if self.save_timer:
            self.save_timer.cancel()
        self.save_timer = threading.Timer(0.8, lambda: hpcam.save_profile(self.profile))
        self.save_timer.daemon = True
        self.save_timer.start()

    def _restart_capture(self):
        with self.lock:
            if not self.cam or not (self.preview_on or self.virtual_on):
                self.capture.stop()
                return
            lb = loopback_device()[0] if self.virtual_on else None
            v = self.profile['virtual']
            self.capture.start(self.cam.dev, lb, v['denoise'], v['sharpen'])

    # ----- background loops -----
    def _housekeeping(self):
        while True:
            with self.lock:
                if self.cam is None:
                    dev = hpcam.find_device()
                    if dev:
                        try:
                            self.cam = hpcam.Cam(dev)
                            hpcam.apply_profile(self.cam, self.profile)
                            self._restart_capture()
                        except (OSError, RuntimeError):
                            self.cam = None
                else:
                    self._cam_do(lambda c: hpcam.ensure_profile(c, self.profile))
                    if (self.preview_on or self.virtual_on) and not self.capture.running() \
                            and not self.capture.error:
                        self._restart_capture()
                    if self.virtual_on and not loopback_device()[0]:
                        self.virtual_on = False
                        self._restart_capture()
            time.sleep(2)

    def _button_loop(self):
        while True:
            pressed = bool(self._cam_do(lambda c: c.button_pressed()))
            if pressed and not self.btn_was:
                self.snapshot(source='camera button')
            self.btn_was = pressed
            time.sleep(0.12)

    def on_stats(self, small):
        """Called from the capture thread with each small RGB frame."""
        means, _ = hpcam.neutral_means(small)
        r, g, b = means
        hist = [np.histogram(small[..., c], bins=48, range=(0, 256))[0].tolist() for c in range(3)]
        now = time.time()
        jseq = self.capture.jseq
        self._fps_n += jseq - self._last_jseq
        self._last_jseq = jseq
        if now - self._fps_t >= 1:
            self.stats['fps'] = self._fps_n / (now - self._fps_t)
            self._fps_t, self._fps_n = now, 0
        self.stats.update(luma=float(small.mean()), rg=float(r / g), bg=float(b / g), hist=hist)
        if self.balance_left > 0:
            if abs(r / g - 1) < 0.015 and abs(b / g - 1) < 0.015:
                self.balance_left = 0
                self.toast('White balance set')
            elif now - self.last_awb > 0.5:
                self.last_awb = now
                self.balance_left -= 1
                self._set_gains(hpcam.awb_step(self.profile['gains'], means, damping=0.6))
                if self.balance_left == 0:
                    self.toast('White balance set')
        elif self.profile.get('awb') and now - self.last_awb > 1.5:
            self.last_awb = now
            if abs(r / g - 1) > 0.025 or abs(b / g - 1) > 0.025:
                self._set_gains(hpcam.awb_step(self.profile['gains'], means, damping=0.3))

    def _set_gains(self, g):
        with self.lock:
            self.profile['gains'] = [max(0x10, min(0xff, int(round(v)))) for v in g]
            gg = list(self.profile['gains'])
        self._cam_do(lambda c: c.set_gains(gg))
        self._schedule_save()

    # ----- API -----
    def state(self):
        with self.lock:
            lb, lb_name = loopback_device()
            if not self.cam:
                cam_state = 'absent'
            elif self.capture.running() and self.capture.jpeg is not None:
                cam_state = 'live'
            elif self.capture.running():
                cam_state = 'starting'
            elif self.capture.error:
                cam_state = 'busy'
            else:
                cam_state = 'paused'
            return {
                'camera': cam_state, 'device': self.cam.dev if self.cam else None,
                'error': self.capture.error, 'preview': self.preview_on, 'virtual': self.virtual_on,
                'loopback': lb, 'loopback_name': lb_name, 'service': self.service_enabled(),
                'profile': self.profile, 'stats': self.stats, 'events': self.events,
                'balancing': self.balance_left > 0,
            }

    def set(self, key, value):
        with self.lock:
            if key in hpcam.CID:
                v = int(value)
                self.profile['uvc'][key] = v
                self._cam_do(lambda c: c.set_ctrl(key, v))
            elif key in ('gain_r', 'gain_g', 'gain_b'):
                i = ('gain_r', 'gain_g', 'gain_b').index(key)
                g = list(self.profile['gains'])
                g[i] = float(value) * 64
                self._set_gains(g)
                return
            elif key == 'awb':
                self.profile['awb'] = bool(value)
            elif key in ('denoise', 'sharpen'):
                self.profile['virtual'][key] = round(float(value), 2)
                if self.virtual_on:
                    self._restart_capture()
            else:
                raise KeyError(key)
            self._schedule_save()

    def action(self, name):
        with self.lock:
            if name == 'snapshot':
                return self.snapshot()
            if name == 'balance':
                if not self.capture.running():
                    raise RuntimeError('Turn on the preview first')
                self.balance_left = 10
                self.last_awb = 0
            elif name in ('preview_on', 'preview_off'):
                self.preview_on = name == 'preview_on'
                self.capture.error = ''
                self._restart_capture()
            elif name in ('virtual_on', 'virtual_off'):
                if name == 'virtual_on' and not loopback_device()[0]:
                    raise RuntimeError('No virtual camera device. Load v4l2loopback first')
                self.virtual_on = name == 'virtual_on'
                self.capture.error = ''
                self._restart_capture()
            elif name == 'reset':
                self.profile.update(gains=[64, 64, 64], awb=False,
                                    uvc=dict(hpcam.UVC_DEFAULTS))
                self._cam_do(lambda c: hpcam.apply_profile(c, self.profile))
                self._schedule_save()
                self.toast('Camera defaults restored')
            elif name in ('service_on', 'service_off'):
                self.set_service(name == 'service_on')
            elif name == 'open_photos':
                os.makedirs(photo_dir(), exist_ok=True)
                subprocess.Popen(['xdg-open', photo_dir()])
            else:
                raise KeyError(name)
        return None

    def snapshot(self, source=None):
        jpeg = self.capture.jpeg
        if jpeg is None:
            self.toast('Turn on the preview to take photos')
            return None
        os.makedirs(photo_dir(), exist_ok=True)
        path = os.path.join(photo_dir(), time.strftime('hpcam-%Y%m%d-%H%M%S.jpg'))
        with open(path, 'wb') as f:
            f.write(jpeg)
        self.toast('Photo saved: %s' % os.path.basename(path))
        return path

    def service_enabled(self):
        now = time.time()
        if now - getattr(self, '_svc_t', 0) > 5:
            r = subprocess.run(['systemctl', '--user', 'is-enabled', 'hpcam.service'],
                               capture_output=True, text=True)
            self._svc, self._svc_t = r.stdout.strip() == 'enabled', now
        return self._svc

    def set_service(self, on):
        if on:
            os.makedirs(os.path.dirname(SERVICE), exist_ok=True)
            with open(SERVICE, 'w') as f:
                f.write('[Unit]\nDescription=HP USB Webcam: keep tuned settings applied\n\n'
                        '[Service]\nExecStart=%s %s run\nRestart=on-failure\nRestartSec=30\n\n'
                        '[Install]\nWantedBy=default.target\n'
                        % (sys.executable, os.path.join(HERE, 'hpcam.py')))
            subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
            subprocess.run(['systemctl', '--user', 'enable', '--now', 'hpcam.service'], check=True)
            self._svc_t = 0
            self.toast('Settings will be kept applied in the background')
        else:
            subprocess.run(['systemctl', '--user', 'disable', '--now', 'hpcam.service'], check=True)
            self._svc_t = 0
            self.toast('Background service stopped')

    def shutdown(self):
        self.capture.stop()
        if self.save_timer:
            self.save_timer.cancel()
        hpcam.save_profile(self.profile)


STATIC = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
          '.js': 'text/javascript; charset=utf-8', '.svg': 'image/svg+xml'}


def make_handler(ctl, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _authed(self, q):
            return secrets.compare_digest(self.headers.get('X-HPCam-Token', '') or q.get('t', [''])[0], token)

        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path in ('/', '/index.html'):
                html = open(os.path.join(UI_DIR, 'index.html'), encoding='utf-8').read()
                body = html.replace('__HPCAM_TOKEN__', token).encode()
                self.send_response(200)
                self.send_header('Content-Type', STATIC['.html'])
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if u.path.startswith('/ui/'):
                name = os.path.basename(u.path)
                path = os.path.join(UI_DIR, name)
                ext = os.path.splitext(name)[1]
                if ext not in STATIC or not os.path.isfile(path):
                    return self.send_error(404)
                body = open(path, 'rb').read()
                self.send_response(200)
                self.send_header('Content-Type', STATIC[ext])
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not self._authed(q):
                return self.send_error(403)
            if u.path == '/api/state':
                return self._json(200, ctl.state())
            if u.path == '/stream.mjpg':
                return self._stream()
            if u.path == '/events':
                return self._events()
            self.send_error(404)

        def do_POST(self):
            u = urlparse(self.path)
            if not self._authed({}):
                return self.send_error(403)
            try:
                data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0)) or 2) or b'{}')
                if u.path == '/api/set':
                    ctl.set(data['key'], data['value'])
                elif u.path == '/api/action':
                    ctl.action(data['name'])
                else:
                    return self.send_error(404)
                self._json(200, {'ok': True})
            except (KeyError, ValueError) as e:
                self._json(400, {'ok': False, 'error': 'Unknown setting %s' % e})
            except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
                self._json(409, {'ok': False, 'error': str(e)})

        def _stream(self):
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=hpcamframe')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            cap, seen = ctl.capture, -1
            try:
                while True:
                    with cap.cond:
                        cap.cond.wait_for(lambda: cap.jseq != seen and cap.jpeg is not None, timeout=5)
                        jpeg, seen = cap.jpeg, cap.jseq
                    if jpeg is None:
                        continue
                    self.wfile.write(b'--hpcamframe\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n'
                                     % len(jpeg) + jpeg + b'\r\n')
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _events(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            try:
                while True:
                    self.wfile.write(b'data: ' + json.dumps(ctl.state()).encode() + b'\n\n')
                    self.wfile.flush()
                    time.sleep(0.5)
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Handler


def serve(port=0):
    ctl = Controller()
    token = secrets.token_urlsafe(18)
    srv = ThreadingHTTPServer(('127.0.0.1', port), make_handler(ctl, token))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return ctl, srv, 'http://127.0.0.1:%d/' % srv.server_address[1]


if __name__ == '__main__':
    ctl, srv, url = serve(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
    print(url, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        ctl.shutdown()
