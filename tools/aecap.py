#!/usr/bin/env python3
"""Hold only exposure (1:56-57) at a cap and let the AE loop drive gain (1:58). Also saves a frame
per setting and reports noise (std of a flat patch) and edge sharpness."""
import os, sys, threading, time, subprocess
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import hpcam  # noqa: E402
OUT = sys.argv[1] if len(sys.argv) > 1 else '/tmp'
cam = hpcam.Cam(hpcam.find_device())
W, H = 320, 240
proc = subprocess.Popen(['ffmpeg', '-loglevel', 'quiet', '-f', 'v4l2', '-input_format', 'mjpeg', '-video_size', '640x480',
                         '-i', cam.dev, '-vf', 'fps=10,scale=%d:%d' % (W, H), '-pix_fmt', 'gray', '-f', 'rawvideo', 'pipe:1'],
                        stdout=subprocess.PIPE)
frame = {'f': None}
def reader():
    while True:
        b = proc.stdout.read(W * H)
        if len(b) < W * H: return
        frame['f'] = np.frombuffer(b, np.uint8).reshape(H, W).astype(float)
threading.Thread(target=reader, daemon=True).start()
time.sleep(5)

def run(cap, secs=8):
    t = time.time(); ls, gs, es = [], [], []
    while time.time() - t < secs:
        if cap:
            r = cam.read(1, 0x56, 2)
            if r[0] + 256 * r[1] > cap:
                cam.write(1, 0x56, cap & 0xff); cam.write(1, 0x57, cap >> 8)
        f = frame['f']; ls.append(f.mean())
        r = cam.read(1, 0x56, 3); es.append(r[0] + 256 * r[1]); gs.append(r[2])
        time.sleep(0.1)
    f = frame['f']
    lap = np.abs(4 * f[1:-1, 1:-1] - f[:-2, 1:-1] - f[2:, 1:-1] - f[1:-1, :-2] - f[1:-1, 2:])
    flat = np.diff(f, axis=1)[np.abs(np.diff(f, axis=1)) < 12]
    from PIL import Image
    Image.fromarray(f.astype(np.uint8)).save(os.path.join(OUT, 'cap_%s.png' % (cap or 'free')))
    l = np.array(ls[20:])
    print('cap %-5s luma %.1f +- %.1f  exp %s  gain first/last %d/%d  noise %.2f  edge %.1f'
          % (cap or 'free', l.mean(), l.std(), (min(es[20:]), max(es[20:])), gs[0], gs[-1], flat.std(), lap.mean()), flush=True)

run(None)
for cap in (250, 180, 130):
    run(cap)
    run(None, 5)
proc.terminate()
