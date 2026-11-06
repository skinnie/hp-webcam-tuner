#!/usr/bin/env python3
"""HP Webcam tuner - GTK 3 front end for hpcam.py (HP USB Webcam, USB 03f0:8007)."""
import glob, os, subprocess, sys, threading, time

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hpcam  # noqa: E402

PW, PH = 640, 480
PHOTO_DIR = os.path.join(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
                         or os.path.expanduser('~/Pictures'), 'HP Webcam')
SERVICE = os.path.expanduser('~/.config/systemd/user/hpcam.service')

# (key, label, min, max, step, digits)
PICTURE = [('brightness', 'Brightness', 0, 255, 1, 0),
           ('contrast', 'Contrast', 0, 100, 1, 0),
           ('gamma', 'Gamma (lower = brighter)', 40, 100, 1, 0),
           ('saturation', 'Saturation', 0, 200, 1, 0),
           ('hue', 'Hue', -180, 180, 1, 0),
           ('sharpness', 'Sharpness', 0, 10, 1, 0),
           ('backlight', 'Backlight compensation', 0, 5, 1, 0)]

CSS = b"""
.preview { background-color: #111; }
.section { font-weight: bold; margin-top: 10px; }
.hint { font-size: 0.9em; opacity: 0.7; }
.statusline { font-family: monospace; font-size: 0.9em; opacity: 0.8; }
"""


def loopback_device():
    for d in sorted(glob.glob('/sys/class/video4linux/video*')):
        try:
            name = open(d + '/name').read()
        except OSError:
            continue
        if 'Dummy' in name or 'Loopback' in name or 'tuned' in name:
            return '/dev/' + os.path.basename(d)
    return None


class Preview:
    """ffmpeg capture in a thread; keeps the latest RGB frame. Optionally feeds a loopback."""

    def __init__(self):
        self.proc = None
        self.frame = None
        self.seq = 0
        self.error = ''
        self.lock = threading.Lock()

    def start(self, dev, loopback=None, denoise=0.0, sharpen=0.0):
        self.stop()
        chain = []
        if denoise > 0:
            chain.append('hqdn3d=%.2f:%.2f:%.2f:%.2f' % (denoise, denoise * .75, denoise * 1.5, denoise * 1.5))
        if sharpen > 0:
            chain.append('unsharp=5:5:%.2f' % sharpen)
        cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error', '-f', 'v4l2', '-input_format', 'mjpeg',
               '-video_size', '%dx%d' % (PW, PH), '-framerate', '30', '-i', dev]
        if loopback:
            pre = (','.join(chain) + ',') if chain else ''
            cmd += ['-filter_complex', '[0:v]%ssplit=2[a][b];[a]format=yuyv422[out];'
                    '[b]fps=15,format=rgb24[pv]' % pre,
                    '-map', '[out]', '-f', 'v4l2', loopback, '-map', '[pv]', '-f', 'rawvideo', 'pipe:1']
        else:
            cmd += ['-vf', 'fps=15,format=rgb24', '-f', 'rawvideo', 'pipe:1']
        self.error = ''
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, proc):
        n = PW * PH * 3
        while True:
            buf = proc.stdout.read(n)
            if not buf or len(buf) < n:
                break
            with self.lock:
                self.frame = buf
                self.seq += 1
        err = proc.stderr.read().decode(errors='replace').strip()
        if proc is self.proc:
            self.error = err.splitlines()[-1] if err else 'capture stopped'

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
        with self.lock:
            self.frame = None

    def latest(self):
        with self.lock:
            return self.frame, self.seq


class TunerUI:
    def __init__(self):
        self.profile = hpcam.load_profile()
        self.profile.setdefault('virtual', {'denoise': 3.0, 'sharpen': 0.5})
        self.cam = None
        self.preview = Preview()
        self.updating = False      # suppress handlers while code moves sliders
        self.save_id = 0
        self.last_seq = -1
        self.pixbuf = None
        self.hist = None
        self.btn_was = False
        self.fps_t, self.fps_n, self.fps = time.time(), 0, 0.0
        self.last_awb = 0.0
        self.build()
        self.load_into_widgets()
        GLib.timeout_add(66, self.tick)
        GLib.timeout_add(120, self.poll_button)
        GLib.timeout_add(2000, self.housekeeping)
        self.housekeeping()

    # ---------- layout ----------
    def build(self):
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        # left: preview + histogram + status
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=10)
        overlay = Gtk.Overlay()
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(480, 360)
        self.area.set_hexpand(True)
        self.area.set_vexpand(True)
        self.area.get_style_context().add_class('preview')
        self.area.connect('draw', self.draw_preview)
        overlay.add(self.area)
        self.toast = Gtk.Revealer(halign=Gtk.Align.CENTER, valign=Gtk.Align.START)
        self.toast_label = Gtk.Label()
        tbox = Gtk.Box()
        tbox.get_style_context().add_class('app-notification')
        tbox.add(self.toast_label)
        self.toast.add(tbox)
        overlay.add_overlay(self.toast)
        left.pack_start(overlay, True, True, 0)

        self.hist_area = Gtk.DrawingArea()
        self.hist_area.set_size_request(-1, 70)
        self.hist_area.connect('draw', self.draw_hist)
        left.pack_start(self.hist_area, False, False, 0)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class('statusline')
        left.pack_start(self.status, False, False, 0)
        root.pack_start(left, True, True, 0)
        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        # right: controls
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_size_request(340, -1)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=12)
        scroller.add(panel)
        root.pack_start(scroller, False, False, 0)

        self.scales = {}
        self.section(panel, 'Picture')
        for key, label, lo, hi, step, digits in PICTURE:
            self.scales[key] = self.slider(panel, label, lo, hi, step, digits, self.on_uvc, key)
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label='Light flicker', xalign=0), True, True, 0)
        self.plf = Gtk.ComboBoxText()
        for i, t in (('0', 'Off'), ('1', '50 Hz'), ('2', '60 Hz')):
            self.plf.append(i, t)
        self.plf.connect('changed', self.on_plf)
        row.pack_start(self.plf, False, False, 0)
        panel.pack_start(row, False, False, 4)

        self.section(panel, 'Colour')
        self.awb = self.switch_row(panel, 'Automatic white balance', self.on_awb)
        self.gain_scales = []
        for i, name in enumerate(('Red', 'Green', 'Blue')):
            self.gain_scales.append(self.slider(panel, name + ' gain', 0.25, 3.98, 0.01, 2, self.on_gain, i))
        bal = Gtk.Button(label='Balance once on what the camera sees')
        bal.connect('clicked', self.on_balance_once)
        panel.pack_start(bal, False, False, 4)
        h = Gtk.Label(label='The camera has no white balance of its own; these are its hidden colour gains.',
                      xalign=0, wrap=True)
        h.get_style_context().add_class('hint')
        panel.pack_start(h, False, False, 0)

        self.section(panel, 'Virtual camera')
        self.virt = self.switch_row(panel, 'Send to virtual camera', self.on_virtual)
        self.denoise = self.slider(panel, 'Noise reduction', 0, 8, 0.5, 1, self.on_virtual_param, 'denoise')
        self.sharpen = self.slider(panel, 'Extra sharpening', 0, 1.5, 0.05, 2, self.on_virtual_param, 'sharpen')
        self.virt_hint = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.virt_hint.get_style_context().add_class('hint')
        panel.pack_start(self.virt_hint, False, False, 0)

        self.section(panel, 'Startup')
        self.autostart = self.switch_row(panel, 'Keep settings applied (background service)', self.on_autostart)

        self.live = Gtk.ToggleButton()
        self.live.add(Gtk.Image.new_from_icon_name('media-playback-start-symbolic', Gtk.IconSize.BUTTON))
        self.live.set_tooltip_text('Live preview (turn off so other apps can use the camera)')
        self.live.set_active(True)
        self.live.connect('toggled', lambda *_: self.restart_preview())
        self.content = root

    def section(self, box, title):
        l = Gtk.Label(label=title, xalign=0)
        l.get_style_context().add_class('section')
        box.pack_start(l, False, False, 2)

    def slider(self, box, label, lo, hi, step, digits, cb, key):
        box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
        s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        s.set_digits(digits)
        s.set_value_pos(Gtk.PositionType.RIGHT)
        s.connect('value-changed', cb, key)
        box.pack_start(s, False, False, 0)
        return s

    def switch_row(self, box, label, cb):
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label=label, xalign=0, wrap=True), True, True, 0)
        sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        sw.connect('notify::active', cb)
        row.pack_start(sw, False, False, 0)
        box.pack_start(row, False, False, 4)
        return sw

    def header(self, window):
        hb = Gtk.HeaderBar(show_close_button=True, title='HP Webcam')
        self.headerbar = hb
        shot = Gtk.Button.new_from_icon_name('camera-photo-symbolic', Gtk.IconSize.BUTTON)
        shot.set_tooltip_text('Take a photo (the button on the camera works too)')
        shot.connect('clicked', lambda *_: self.snapshot())
        hb.pack_start(shot)
        hb.pack_start(self.live)

        menu = Gtk.Popover()
        mbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=6)
        for text, cb in (('Reset to camera defaults', self.on_reset),
                         ('Open photos folder', self.on_open_photos),
                         ('Add to applications menu', self.on_install_launcher)):
            b = Gtk.ModelButton(text=text)
            b.connect('clicked', cb)
            mbox.pack_start(b, False, False, 0)
        mbox.show_all()
        menu.add(mbox)
        mb = Gtk.MenuButton(popover=menu)
        mb.add(Gtk.Image.new_from_icon_name('open-menu-symbolic', Gtk.IconSize.BUTTON))
        hb.pack_end(mb)
        window.set_titlebar(hb)

    # ---------- state ----------
    def load_into_widgets(self):
        self.updating = True
        u = self.profile['uvc']
        for key, *_ in PICTURE:
            self.scales[key].set_value(u.get(key, hpcam.UVC_DEFAULTS.get(key, 0)))
        self.plf.set_active_id(str(u.get('power_line', 1)))
        for s, g in zip(self.gain_scales, self.profile['gains']):
            s.set_value(g / 64)
        self.awb.set_active(self.profile.get('awb', False))
        for s in self.gain_scales:
            s.set_sensitive(not self.awb.get_active())
        self.denoise.set_value(self.profile['virtual']['denoise'])
        self.sharpen.set_value(self.profile['virtual']['sharpen'])
        self.autostart.set_active(self.service_enabled())
        self.updating = False

    def schedule_save(self):
        if self.save_id:
            GLib.source_remove(self.save_id)
        self.save_id = GLib.timeout_add(800, self._save)

    def _save(self):
        self.save_id = 0
        hpcam.save_profile(self.profile)
        return False

    def with_cam(self, fn):
        if not self.cam:
            return
        try:
            fn(self.cam)
        except OSError:
            self.drop_cam()

    def drop_cam(self):
        try:
            self.cam.close()
        except Exception:
            pass
        self.cam = None

    # ---------- handlers ----------
    def on_uvc(self, scale, key):
        if self.updating:
            return
        v = int(round(scale.get_value()))
        self.profile['uvc'][key] = v
        self.with_cam(lambda c: c.set_ctrl(key, v))
        self.schedule_save()

    def on_plf(self, combo):
        if self.updating:
            return
        v = int(combo.get_active_id())
        self.profile['uvc']['power_line'] = v
        self.with_cam(lambda c: c.set_ctrl('power_line', v))
        self.schedule_save()

    def on_gain(self, scale, i):
        if self.updating:
            return
        self.profile['gains'][i] = int(round(scale.get_value() * 64))
        g = list(self.profile['gains'])
        self.with_cam(lambda c: c.set_gains(g))
        self.schedule_save()

    def set_gains_from_code(self, g):
        self.profile['gains'] = [max(0x10, min(0xff, int(round(v)))) for v in g]
        self.updating = True
        for s, v in zip(self.gain_scales, self.profile['gains']):
            s.set_value(v / 64)
        self.updating = False
        gg = list(self.profile['gains'])
        self.with_cam(lambda c: c.set_gains(gg))
        self.schedule_save()

    def on_awb(self, sw, _):
        for s in self.gain_scales:
            s.set_sensitive(not sw.get_active())
        if self.updating:
            return
        self.profile['awb'] = sw.get_active()
        self.schedule_save()

    def on_balance_once(self, _):
        frame, _ = self.preview.latest()
        if frame is None:
            self.show_toast('Turn on the live preview first')
            return
        self.balance_steps = 8
        GLib.timeout_add(400, self._balance_step)

    def _balance_step(self):
        frame, _ = self.preview.latest()
        if frame is None or self.balance_steps <= 0:
            return False
        means, _ = hpcam.neutral_means(np.frombuffer(frame, np.uint8).reshape(PH, PW, 3)[::8, ::8])
        r, g, b = means
        if abs(r / g - 1) < 0.015 and abs(b / g - 1) < 0.015:
            self.show_toast('White balance done')
            return False
        self.set_gains_from_code(hpcam.awb_step(self.profile['gains'], means, damping=0.6))
        self.balance_steps -= 1
        return self.balance_steps > 0

    def on_virtual(self, sw, _):
        if self.updating:
            return
        if sw.get_active() and not loopback_device():
            self.updating = True
            sw.set_active(False)
            self.updating = False
            self.show_toast('No virtual camera device: load v4l2loopback first')
            return
        if sw.get_active() and not self.live.get_active():
            self.live.set_active(True)   # restarts preview
        else:
            self.restart_preview()

    def on_virtual_param(self, scale, key):
        if self.updating:
            return
        self.profile['virtual'][key] = round(scale.get_value(), 2)
        self.schedule_save()
        if self.virt.get_active():
            if getattr(self, 'vp_id', 0):
                GLib.source_remove(self.vp_id)
            self.vp_id = GLib.timeout_add(600, self._restart_once)

    def _restart_once(self):
        self.vp_id = 0
        self.restart_preview()
        return False

    def on_autostart(self, sw, _):
        if self.updating:
            return
        try:
            if sw.get_active():
                os.makedirs(os.path.dirname(SERVICE), exist_ok=True)
                with open(SERVICE, 'w') as f:
                    f.write('[Unit]\nDescription=HP USB Webcam: keep tuned settings applied\n\n'
                            '[Service]\nExecStart=%s %s run\nRestart=on-failure\nRestartSec=30\n\n'
                            '[Install]\nWantedBy=default.target\n'
                            % (sys.executable, os.path.join(HERE, 'hpcam.py')))
                subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
                subprocess.run(['systemctl', '--user', 'enable', '--now', 'hpcam.service'], check=True)
                self.show_toast('Background service on')
            else:
                subprocess.run(['systemctl', '--user', 'disable', '--now', 'hpcam.service'], check=True)
                self.show_toast('Background service off')
        except (OSError, subprocess.CalledProcessError) as e:
            self.show_toast('Could not change the service: %s' % e)

    def service_enabled(self):
        r = subprocess.run(['systemctl', '--user', 'is-enabled', 'hpcam.service'],
                           capture_output=True, text=True)
        return r.stdout.strip() == 'enabled'

    def on_reset(self, *_):
        keep = {k: self.profile.get(k) for k in ('virtual',)}
        self.profile = {'gains': [64, 64, 64], 'uvc': dict(hpcam.UVC_DEFAULTS, power_line=1),
                        'awb': False, **keep}
        self.load_into_widgets()
        self.with_cam(lambda c: hpcam.apply_profile(c, self.profile))
        self.schedule_save()
        self.show_toast('Camera defaults restored')

    def on_open_photos(self, *_):
        os.makedirs(PHOTO_DIR, exist_ok=True)
        Gtk.show_uri_on_window(None, GLib.filename_to_uri(PHOTO_DIR), Gdk.CURRENT_TIME)

    def on_install_launcher(self, *_):
        path = os.path.expanduser('~/.local/share/applications/hpcam.desktop')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write('[Desktop Entry]\nType=Application\nName=HP Webcam\n'
                    'Comment=Tune the HP USB Webcam picture\n'
                    'Exec=%s %s\nIcon=camera-web\nCategories=AudioVideo;Video;\n'
                    % (sys.executable, os.path.abspath(__file__)))
        self.show_toast('Added "HP Webcam" to the applications menu')

    # ---------- camera + preview ----------
    def housekeeping(self):
        if self.cam is None:
            dev = hpcam.find_device()
            if dev:
                try:
                    self.cam = hpcam.Cam(dev)
                    hpcam.apply_profile(self.cam, self.profile)
                    self.restart_preview()
                except (OSError, RuntimeError):
                    self.cam = None
        else:
            # after a replug the chip comes up with factory values; put ours back
            self.with_cam(lambda c: hpcam.ensure_profile(c, self.profile))
        if self.cam and self.live.get_active() and not self.preview.running():
            self.restart_preview()
        lb = loopback_device()
        if lb:
            self.virt_hint.set_text('Apps see it as "%s" (%s).' % (
                open('/sys/class/video4linux/%s/name' % os.path.basename(lb)).read().strip(), lb))
        else:
            self.virt_hint.set_text('Needs the v4l2loopback module, once per boot:\n'
                                    'sudo modprobe v4l2loopback card_label="HP Webcam (tuned)" exclusive_caps=1')
        self.update_title()
        return True

    def restart_preview(self):
        want = self.cam is not None and (self.live.get_active() or self.virt.get_active())
        if not want:
            self.preview.stop()
            self.pixbuf = None
            self.area.queue_draw()
            return
        lb = loopback_device() if self.virt.get_active() else None
        v = self.profile['virtual']
        self.preview.start(self.cam.dev, lb, v['denoise'] if lb else 0, v['sharpen'] if lb else 0)

    def update_title(self):
        hb = getattr(self, 'headerbar', None)
        if not hb:
            return
        if not self.cam:
            hb.set_subtitle('Camera not connected')
        elif self.preview.running():
            hb.set_subtitle('%s · live%s' % (self.cam.dev, ' · virtual camera on' if self.virt.get_active() else ''))
        elif self.live.get_active() and self.preview.error:
            hb.set_subtitle('Camera busy: %s' % self.preview.error[:60])
        else:
            hb.set_subtitle('%s · preview off' % self.cam.dev)

    def tick(self):
        frame, seq = self.preview.latest()
        if frame is not None and seq != self.last_seq:
            self.last_seq = seq
            self.pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(frame), GdkPixbuf.Colorspace.RGB,
                                                          False, 8, PW, PH, PW * 3)
            self.area.queue_draw()
            self.fps_n += 1
            small = np.frombuffer(frame, np.uint8).reshape(PH, PW, 3)[::4, ::4]
            if self.fps_n % 3 == 0:
                self.hist = [np.histogram(small[..., c], bins=64, range=(0, 256))[0] for c in range(3)]
                self.hist_area.queue_draw()
            now = time.time()
            if now - self.fps_t > 1:
                self.fps = self.fps_n / (now - self.fps_t)
                self.fps_t, self.fps_n = now, 0
                means, _ = hpcam.neutral_means(small[::2, ::2])
                r, g, b = means
                self.status.set_text('%.0f fps   brightness %3.0f   R/G %.2f   B/G %.2f   gains %.2f %.2f %.2f' % (
                    self.fps, small.mean(), r / g, b / g, *[x / 64 for x in self.profile['gains']]))
                if self.awb.get_active() and now - self.last_awb > 1.5:
                    self.last_awb = now
                    if abs(r / g - 1) > 0.025 or abs(b / g - 1) > 0.025:
                        self.set_gains_from_code(hpcam.awb_step(self.profile['gains'], means, damping=0.3))
        return True

    def poll_button(self):
        if self.cam:
            try:
                pressed = self.cam.button_pressed()
            except OSError:
                pressed = False
            if pressed and not self.btn_was:
                self.snapshot()
            self.btn_was = pressed
        return True

    def snapshot(self):
        if self.pixbuf is None:
            self.show_toast('Turn on the live preview to take photos')
            return
        os.makedirs(PHOTO_DIR, exist_ok=True)
        path = os.path.join(PHOTO_DIR, time.strftime('hpcam-%Y%m%d-%H%M%S.png'))
        self.pixbuf.savev(path, 'png', [], [])
        self.show_toast('Saved %s' % os.path.basename(path))

    def show_toast(self, text):
        self.toast_label.set_text(text)
        self.toast.set_reveal_child(True)
        if getattr(self, 'toast_id', 0):
            GLib.source_remove(self.toast_id)
        self.toast_id = GLib.timeout_add(2500, self._hide_toast)

    def _hide_toast(self):
        self.toast.set_reveal_child(False)
        self.toast_id = 0
        return False

    # ---------- drawing ----------
    def draw_preview(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        cr.set_source_rgb(0.07, 0.07, 0.07)
        cr.paint()
        if self.pixbuf is None:
            if not self.cam:
                msg = 'Plug in the HP USB Webcam'
            elif not self.live.get_active():
                msg = 'Preview is off. Other apps can use the camera.'
            elif self.preview.error:
                msg = 'Camera is in use by another app'
            else:
                msg = 'Starting camera...'
            cr.set_source_rgb(0.7, 0.7, 0.7)
            cr.select_font_face('Sans')
            cr.set_font_size(15)
            ext = cr.text_extents(msg)
            cr.move_to((w - ext.width) / 2, h / 2)
            cr.show_text(msg)
            return
        s = min(w / PW, h / PH)
        cr.translate((w - PW * s) / 2, (h - PH * s) / 2)
        cr.scale(s, s)
        Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
        cr.paint()

    def draw_hist(self, area, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.12)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        if not self.hist:
            return
        peak = max(float(x.max()) for x in self.hist) or 1
        for hist, rgb in zip(self.hist, ((0.9, 0.25, 0.25), (0.25, 0.8, 0.3), (0.3, 0.45, 0.95))):
            cr.move_to(0, h)
            for i, v in enumerate(hist):
                cr.line_to(i * w / (len(hist) - 1), h - (v / peak) * (h - 4))
            cr.line_to(w, h)
            cr.close_path()
            cr.set_source_rgba(*rgb, 0.4)
            cr.fill()

    def shutdown(self):
        self.preview.stop()
        if self.save_id:
            self._save()


def main():
    shot = None
    if '--screenshot' in sys.argv:   # render off-screen to a PNG (for testing)
        shot = sys.argv[sys.argv.index('--screenshot') + 1]
    ui = TunerUI()
    if shot:
        win = Gtk.OffscreenWindow()
        win.add(ui.content)
        ui.content.set_size_request(1040, int(os.environ.get('SHOT_H', '640')))
        win.show_all()

        def grab():
            pb = win.get_pixbuf()
            pb.savev(shot, 'png', [], [])
            ui.shutdown()
            Gtk.main_quit()
            return False
        GLib.timeout_add(int(float(os.environ.get('SHOT_DELAY', '5')) * 1000), grab)
        Gtk.main()
        return
    win = Gtk.Window(default_width=1040, default_height=640)
    win.set_icon_name('camera-web')
    ui.header(win)
    win.add(ui.content)
    win.connect('destroy', lambda *_: (ui.shutdown(), Gtk.main_quit()))
    win.show_all()
    ui.update_title()
    Gtk.main()


if __name__ == '__main__':
    main()
