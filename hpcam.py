#!/usr/bin/env python3
"""hpcam - image tuning for the HP USB Webcam (AU165AA, USB 03f0:8007, Vimicro bridge).

Talks to the camera's vendor extension unit (see NOTES.md) to set the chip's colour gains,
which the firmware never adjusts on its own (no auto white balance), plus the standard
UVC picture controls. No root needed, except loading v4l2loopback for `virtual`.

  hpcam.py status             show the chip state
  hpcam.py calibrate          auto white balance once (camera must be free), save profile
  hpcam.py apply              write the saved profile to the camera
  hpcam.py run                keep applying the profile whenever the camera shows up
  hpcam.py virtual            continuous AWB + denoise/sharpen into a v4l2loopback camera
  hpcam.py reset              chip gains back to 1.0, UVC controls back to defaults
"""
import argparse, ctypes, fcntl, glob, json, os, struct, subprocess, sys, time

BY_ID = '/dev/v4l/by-id/usb-HP_USB_Webcam_HP_USB_Webcam-video-index0'
XU_UNIT = 4
PROFILE = os.path.expanduser('~/.config/hpcam/profile.json')
LOCK = os.path.join(os.environ.get('XDG_RUNTIME_DIR', '/tmp'), 'hpcam.lock')

# --- register spaces (selector of the XU that reads/writes them) ---
CHIP = 3      # colour pipeline: 0x04 G, 0x05 R, 0x06 B gain (0x40 = 1.0), 0x07-09 offsets, 0x5f mean luma
ISP = 1       # 0x17-0x28 colour matrix, 0xa2-0xab tone curve, 0xb6 sharpness
GAIN_REGS = (0x05, 0x04, 0x06)  # R, G, B (measured: the chip order is G, R, B)

# --- UVC controls (V4L2 ids) ---
CID = {'brightness': 0x980900, 'contrast': 0x980901, 'saturation': 0x980902, 'hue': 0x980903,
       'gamma': 0x980910, 'power_line': 0x980918, 'sharpness': 0x98091b, 'backlight': 0x98091c}
UVC_DEFAULTS = {'brightness': 128, 'contrast': 25, 'saturation': 155, 'hue': 0, 'gamma': 75,
                'sharpness': 6, 'backlight': 0, 'power_line': 2}   # camera's own defaults (60 Hz)
# Picked from test shots (2026-11-06): contrast 55 + gamma 68 keeps midtones where the default
# had them but with real blacks (5th percentile luma 64 -> 56); lower gamma number = brighter.
# Slightly less saturation (the colour matrix is strong) and less over-sharpening.
DEFAULT_PROFILE = {'gains': [0x40, 0x40, 0x40],
                   'uvc': {'contrast': 55, 'gamma': 68, 'saturation': 130, 'sharpness': 4,
                           'brightness': 128, 'backlight': 0, 'power_line': 1}}

_IOC = lambda d, t, nr, size: (d << 30) | (size << 16) | (ord(t) << 8) | nr
UVCIOC_CTRL_QUERY = _IOC(3, 'u', 0x21, 16)
VIDIOC_S_CTRL = _IOC(3, 'V', 28, 8)
VIDIOC_G_CTRL = _IOC(3, 'V', 27, 8)
SET_CUR, GET_CUR, GET_LEN = 0x01, 0x81, 0x85


def find_device():
    if os.path.exists(BY_ID):
        return os.path.realpath(BY_ID)
    for n in sorted(glob.glob('/sys/class/video4linux/video*')):
        if 'HP USB Webcam' in open(n + '/name').read() and open(n + '/index').read().strip() == '0':
            return '/dev/' + os.path.basename(n)
    return None


class Cam:
    def __init__(self, dev):
        self.dev = dev
        self.fd = os.open(dev, os.O_RDWR)
        if struct.unpack('<H', self._q(3, GET_LEN, size=2))[0] != 4:
            raise RuntimeError('extension unit does not look like the Vimicro one')

    def close(self):
        os.close(self.fd)

    def _q(self, sel, query, data=None, size=4):
        buf = ctypes.create_string_buffer(bytes(data) if data else b'\0' * size, size)
        arg = bytearray(struct.pack('BBBxHxxP', XU_UNIT, sel, query, size, ctypes.addressof(buf)))
        fcntl.ioctl(self.fd, UVCIOC_CTRL_QUERY, arg)
        return buf.raw

    # selector 5 = [address, length]; data selectors 1/2/3/7 are separate spaces.
    # While the camera is idle, reads return the active value and writes take effect
    # when streaming starts.
    # A register access is several requests (select address, then read/write), so every
    # process using the camera (GUI, `run` service, CLI) takes the same lock around it.
    def _locked(self):
        lock = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        return lock

    def read(self, space, addr, length=1):
        lock = self._locked()
        try:
            self._q(5, SET_CUR, [addr, length, 0, 0])
            return self._q(space, GET_CUR)[:length]
        finally:
            os.close(lock)

    def write(self, space, addr, value):
        lock = self._locked()
        try:
            self._q(5, SET_CUR, [addr, 1, 0, 0])
            cur = self._q(space, GET_CUR)
            self._q(space, SET_CUR, [addr, value & 0xff, 1, cur[3]])
            time.sleep(0.03)
        finally:
            os.close(lock)

    def button_pressed(self):
        """Physical snapshot button (BM.exe READBT: selector 5, byte 3 == 1)."""
        lock = self._locked()
        try:
            return self._q(5, GET_CUR)[3] == 1
        finally:
            os.close(lock)

    def gains(self):
        g, r, b = self.read(CHIP, 0x04, 3)
        return [r, g, b]

    def set_gains(self, g):
        for reg, v in zip(GAIN_REGS, g):
            self.write(CHIP, reg, max(0x10, min(0xff, int(round(v)))))

    def get_ctrl(self, name):
        b = bytearray(struct.pack('Ii', CID[name], 0))
        fcntl.ioctl(self.fd, VIDIOC_G_CTRL, b)
        return struct.unpack('Ii', b)[1]

    def set_ctrl(self, name, v):
        fcntl.ioctl(self.fd, VIDIOC_S_CTRL, bytearray(struct.pack('Ii', CID[name], int(v))))


def load_profile():
    try:
        p = json.load(open(PROFILE))
        p['uvc'] = {**DEFAULT_PROFILE['uvc'], **p.get('uvc', {})}
        return p
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULT_PROFILE))


def save_profile(p):
    os.makedirs(os.path.dirname(PROFILE), exist_ok=True)
    json.dump(p, open(PROFILE, 'w'), indent=2)


def apply_profile(cam, p):
    # UVC controls first: the white-balance-temperature control would overwrite the blue gain,
    # so it is never touched.
    for k, v in p['uvc'].items():
        cam.set_ctrl(k, v)
    cam.set_gains(p['gains'])


def ensure_profile(cam, p):
    """Re-apply the profile if the chip no longer matches it. Returns True if it did.
    A freshly plugged chip reads all zeros until its first stream, so wait for it to be live."""
    if cam.read(CHIP, 0x5f)[0] == 0 and cam.read(ISP, 0xb6)[0] == 0:
        return False
    if cam.read(ISP, 0xb6)[0] != p['uvc'].get('sharpness', 6) or cam.gains() != list(p['gains']):
        apply_profile(cam, p)
        return True
    return False


# --- frame statistics -------------------------------------------------------
W, H = 80, 60


def neutral_means(frame):
    """Mean R,G,B over pixels that are probably grey/white (grey-world fallback).
    `frame` is raw rgb24 bytes of W x H, or an (h, w, 3) uint8 array."""
    import numpy as np
    if isinstance(frame, (bytes, bytearray)):
        frame = np.frombuffer(frame, np.uint8).reshape(H, W, 3)
    f = frame.astype(np.float32)
    lum = f.mean(axis=2)
    spread = f.max(axis=2) - f.min(axis=2)
    ok = (lum > 40) & (lum < 230) & (f.max(axis=2) < 250) & (spread < 0.35 * lum)
    sel = f[ok] if ok.mean() > 0.05 else f.reshape(-1, 3)
    return sel.mean(axis=0), float(ok.mean())


def awb_step(gains, means, damping=0.6):
    """Move R and B gains so R and B means match G. Green stays as the reference."""
    r, g, b = means
    new = list(gains)
    new[0] = gains[0] * (g / max(r, 1)) ** damping
    new[2] = gains[2] * (g / max(b, 1)) ** damping
    return new


def ffmpeg_capture(dev, extra_outputs=()):
    cmd = ['ffmpeg', '-loglevel', 'error', '-f', 'v4l2', '-input_format', 'mjpeg',
           '-video_size', '640x480', '-framerate', '30', '-i', dev]
    if extra_outputs:
        cmd += extra_outputs
    else:
        cmd += ['-vf', f'fps=10,scale={W}:{H}', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
    return subprocess.Popen(cmd, stdout=subprocess.PIPE)


def read_frame(proc):
    n = W * H * 3
    buf = b''
    while len(buf) < n:
        chunk = proc.stdout.read(n - len(buf))
        if not chunk:
            raise RuntimeError('capture ended')
        buf += chunk
    return buf


# --- commands ---------------------------------------------------------------
def cmd_status(cam, args):
    print('device     ', cam.dev)
    print('RGB gains  ', ' '.join('%.2f' % (v / 64) for v in cam.gains()), '(1.00 = neutral)')
    print('RGB offset ', cam.read(CHIP, 0x07, 3).hex(' '))
    print('mean luma  ', cam.read(CHIP, 0x5f)[0])
    print('sharpness  ', cam.read(ISP, 0xb6)[0])
    print('tone curve ', cam.read(ISP, 0xa2, 4).hex(' '), cam.read(ISP, 0xa6, 4).hex(' '),
          cam.read(ISP, 0xaa, 2).hex(' '))
    print('UVC        ', {k: cam.get_ctrl(k) for k in CID})
    print('profile    ', PROFILE if os.path.exists(PROFILE) else '(none saved, using built-in)')


def cmd_calibrate(cam, args):
    p = load_profile()
    for k, v in p['uvc'].items():
        cam.set_ctrl(k, v)
    gains = [0x40, 0x40, 0x40]
    cam.set_gains(gains)
    proc = ffmpeg_capture(cam.dev)
    try:
        for _ in range(15):  # let auto exposure settle
            read_frame(proc)
        for it in range(20):
            for _ in range(5):  # gains need a few frames to show up
                read_frame(proc)
            means, frac = neutral_means(read_frame(proc))
            r, g, b = means
            print('step %2d  gains %.2f %.2f %.2f  R/G %.3f  B/G %.3f  (neutral px %d%%)' %
                  (it, gains[0] / 64, gains[1] / 64, gains[2] / 64, r / g, b / g, frac * 100))
            if abs(r / g - 1) < 0.015 and abs(b / g - 1) < 0.015:
                break
            gains = awb_step(gains, means)
            cam.set_gains(gains)
            gains = [max(0x10, min(0xff, round(v))) for v in gains]
    finally:
        proc.terminate()
    p['gains'] = gains
    save_profile(p)
    print('saved', PROFILE, 'gains', gains)


def cmd_apply(cam, args):
    apply_profile(cam, load_profile())
    print('applied', PROFILE if os.path.exists(PROFILE) else 'built-in profile')


def cmd_reset(cam, args):
    cam.set_gains([0x40, 0x40, 0x40])
    for k, v in UVC_DEFAULTS.items():
        cam.set_ctrl(k, v)
    print('reset to camera defaults')


def cmd_run(args):
    """Keep the profile applied: after a replug the chip comes back with factory values once
    it starts streaming, and apps may move the white-balance slider (overwrites blue gain)."""
    cam = None
    while True:
        try:
            if cam is None:
                dev = find_device()
                if dev:
                    cam = Cam(dev)
                    print(time.strftime('%H:%M:%S'), 'camera found on', dev, flush=True)
            if cam is not None and ensure_profile(cam, load_profile()):
                print(time.strftime('%H:%M:%S'), 'profile re-applied', flush=True)
        except (OSError, RuntimeError):
            if cam is not None:
                try:
                    cam.close()
                except OSError:
                    pass
            cam = None
        time.sleep(2)


def cmd_virtual(cam, args):
    out = args.output or next((d for d in sorted(glob.glob('/dev/video*'))
                               if 'Dummy' in open('/sys/class/video4linux/%s/name' % os.path.basename(d)).read()
                               or 'Loopback' in open('/sys/class/video4linux/%s/name' % os.path.basename(d)).read()), None)
    if not out:
        sys.exit('no v4l2loopback device. Load it once with:\n'
                 '  sudo modprobe v4l2loopback card_label="HP Webcam (tuned)" exclusive_caps=1')
    p = load_profile()
    apply_profile(cam, p)
    gains = list(p['gains'])
    vf = ('[0:v]split=2[a][b];'
          f'[a]hqdn3d={args.denoise}:{args.denoise * 0.75}:{args.denoise * 1.5}:{args.denoise * 1.5},'
          f'unsharp=5:5:{args.sharpen},format=yuyv422[out];'
          f'[b]fps=5,scale={W}:{H},format=rgb24[st]')
    proc = ffmpeg_capture(cam.dev, ['-filter_complex', vf, '-map', '[out]', '-f', 'v4l2', out,
                                    '-map', '[st]', '-f', 'rawvideo', 'pipe:1'])
    print('virtual camera on', out, '- Ctrl+C to stop', flush=True)
    try:
        n = 0
        while True:
            means, _ = neutral_means(read_frame(proc))
            n += 1
            r, g, b = means
            # slow, dead-banded AWB so colours don't pump
            if n % 3 == 0 and (abs(r / g - 1) > 0.03 or abs(b / g - 1) > 0.03):
                gains = awb_step(gains, means, damping=0.25)
                cam.set_gains(gains)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        p['gains'] = [max(0x10, min(0xff, round(v))) for v in gains]
        save_profile(p)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['status', 'calibrate', 'apply', 'run', 'virtual', 'reset'])
    ap.add_argument('--device', help='camera node (default: find the HP USB Webcam)')
    ap.add_argument('--output', help='v4l2loopback node for `virtual`')
    ap.add_argument('--denoise', type=float, default=3.0, help='virtual: hqdn3d strength')
    ap.add_argument('--sharpen', type=float, default=0.5, help='virtual: unsharp amount')
    args = ap.parse_args()
    if args.command == 'run':
        return cmd_run(args)
    dev = args.device or find_device()
    if not dev:
        sys.exit('HP USB Webcam not found')
    cam = Cam(dev)
    {'status': cmd_status, 'calibrate': cmd_calibrate, 'apply': cmd_apply,
     'reset': cmd_reset, 'virtual': cmd_virtual}[args.command](cam, args)


if __name__ == '__main__':
    main()
