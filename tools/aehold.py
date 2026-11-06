#!/usr/bin/env python3
"""Can exposure (1:56-57, 16-bit LE) and gain (1:58) be held against the AE loop by rewriting
them periodically? Prints luma mean/std and the readback while holding, then releases."""
import os, sys, threading, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import hpcam  # noqa: E402

cam = hpcam.Cam(hpcam.find_device())
proc = hpcam.ffmpeg_capture(cam.dev)
luma = {'v': 0.0, 'n': 0}
def reader():
    while True:
        try:
            luma['v'] = float(np.frombuffer(hpcam.read_frame(proc), np.uint8).mean()); luma['n'] += 1
        except RuntimeError:
            return
threading.Thread(target=reader, daemon=True).start()
time.sleep(5)

def sample(secs, hold=None, period=0.1):
    ls, ex = [], []
    t = time.time()
    while time.time() - t < secs:
        if hold:
            e, g = hold
            cam.write(1, 0x56, e & 0xff); cam.write(1, 0x57, e >> 8); cam.write(1, 0x58, g)
        ls.append(luma['v'])
        r = cam.read(1, 0x56, 3); ex.append((r[0] + 256 * r[1], r[2]))
        time.sleep(period)
    ls = np.array(ls[5:])
    return ls.mean(), ls.std(), ex[-3:]

e0 = cam.read(1, 0x56, 3); E, G = e0[0] + 256 * e0[1], e0[2]
print('free AE      : luma %.1f +- %.1f  exp/gain %s' % sample(4))
for name, hold in (('exp/2 gain*2', (E // 2, min(255, G * 2))),
                   ('exp/4 gain*4', (E // 4, min(255, G * 4))),
                   ('exp/2 same gain', (E // 2, G))):
    m, s, ex = sample(6, hold)
    print('%-13s: luma %.1f +- %.1f  readback %s  (held %d/%d %d)' % (name, m, s, ex, hold[0], hold[1], 0), flush=True)
    print('released     : luma %.1f +- %.1f  exp/gain %s' % sample(4), flush=True)
proc.terminate()
