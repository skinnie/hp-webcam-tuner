#!/usr/bin/env python3
"""Hand-wave test: waits for motion, then alternates free AE and an exposure cap every 8 s
(6 rounds), measuring edge sharpness in the moving areas. Saves a frame per round."""
import json, os, subprocess, sys, threading, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import hpcam  # noqa: E402

OUT = os.path.join(HERE, 'data')
cam = hpcam.Cam(hpcam.find_device())
W, H = 320, 240
proc = subprocess.Popen(['ffmpeg', '-loglevel', 'quiet', '-f', 'v4l2', '-input_format', 'mjpeg', '-video_size', '640x480',
                         '-i', cam.dev, '-vf', 'fps=15,scale=%d:%d' % (W, H), '-pix_fmt', 'gray', '-f', 'rawvideo', 'pipe:1'],
                        stdout=subprocess.PIPE)
st = {'f': None, 'prev': None, 'luma': 0.0}
def reader():
    while True:
        b = proc.stdout.read(W * H)
        if len(b) < W * H:
            return
        f = np.frombuffer(b, np.uint8).reshape(H, W).astype(np.float32)
        st['prev'], st['f'], st['luma'] = st['f'], f, float(f.mean())
threading.Thread(target=reader, daemon=True).start()
time.sleep(4)

# wait for real frames, then for motion (a waving hand) before starting
while st['prev'] is None:
    time.sleep(0.1)
print('waiting for a moving hand (up to 10 min)', flush=True)
t0 = time.time(); streak = 0
while time.time() - t0 < 600:
    f, p = st['f'], st['prev']
    streak = streak + 1 if (np.abs(f - p) > 20).mean() > 0.03 else 0
    if streak >= 8:          # about half a second of sustained motion
        break
    time.sleep(0.07)
else:
    print('no motion seen in 10 min, stopping'); proc.terminate(); sys.exit(1)

# phase 2: wave test, 4 x 10 s alternating free / cap
print('motion seen, wave test starts', flush=True)
CAP = 150
res = []
for i, cap in enumerate((None, CAP, None, CAP, None, CAP)):
    t = time.time(); sharp, motion = [], []
    while time.time() - t < 8:
        if cap:
            r = cam.read(1, 0x56, 2)
            if r[0] + 256 * r[1] > cap:
                cam.write(1, 0x56, cap & 0xff); cam.write(1, 0x57, cap >> 8)
        f, p = st['f'], st['prev']
        if f is not None and p is not None and time.time() - t > 2:
            moving = np.abs(f - p) > 20
            lap = np.abs(4 * f[1:-1, 1:-1] - f[:-2, 1:-1] - f[2:, 1:-1] - f[1:-1, :-2] - f[1:-1, 2:])
            m = moving[1:-1, 1:-1]
            if m.mean() > 0.02:
                sharp.append(float(lap[m].mean())); motion.append(float(m.mean()))
        time.sleep(0.07)
    from PIL import Image
    Image.fromarray(st['f'].astype(np.uint8)).save(os.path.join(OUT, 'wave_%d_%s.png' % (i, cap or 'free')))
    r = cam.read(1, 0x56, 3)
    res.append((cap or 'free', np.mean(sharp) if sharp else 0, len(sharp), np.mean(motion) if motion else 0, r[0] + 256 * r[1], r[2]))
    print('%-5s edge-sharpness in moving areas %.2f (%d frames, motion %.0f%%)  exp %d gain %d'
          % (res[-1][0], res[-1][1], res[-1][2], 100 * res[-1][3], res[-1][4], res[-1][5]), flush=True)
proc.terminate()
