#!/usr/bin/env python3
"""Stage-2b: look for the AE target / AE enable. For each candidate byte in space 1, change it,
let the AE loop settle 3 s, record steady luma and the exposure value (1:56-57), then restore."""
import os, sys, threading, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import hpcam  # noqa: E402

cam = hpcam.Cam(hpcam.find_device())
proc = hpcam.ffmpeg_capture(cam.dev)
luma = {'v': 0.0}
def reader():
    while True:
        try:
            luma['v'] = float(np.frombuffer(hpcam.read_frame(proc), np.uint8).mean())
        except RuntimeError:
            return
threading.Thread(target=reader, daemon=True).start()
time.sleep(5)

def settle(secs=3.0):
    time.sleep(secs - 1)
    ls, ex = [], []
    for _ in range(4):
        ls.append(luma['v'])
        e = cam.read(1, 0x56, 3)
        ex.append(e[0] + 256 * e[1])
        time.sleep(0.25)
    return np.mean(ls), int(np.mean(ex)), cam.read(1, 0x58)[0]

SPACE = int(os.environ.get("SPACE", "1"))
addrs = [int(a, 0) for a in sys.argv[1:]] or (list(range(0x00, 0x17)) + list(range(0x40, 0x56)) + [0x59, 0x5a, 0x5b])
L0, E0, G0 = settle(2)
print('baseline luma %.0f exp %d gain %d' % (L0, E0, G0), flush=True)
for a in addrs:
    orig = cam.read(SPACE, a)[0]
    tries = [orig // 2, min(255, orig * 2)] if orig > 1 else [orig ^ 1, orig | 0x80]
    out = []
    for v in tries:
        if v == orig:
            continue
        cam.write(SPACE, a, v)
        L, E, G = settle()
        back = cam.read(SPACE, a)[0]
        cam.write(SPACE, a, orig)
        out.append('->%3d: luma %5.1f exp %4d gain %3d %s' % (v, L, E, G, '' if back == v else '(reverted to %d)' % back))
        Lr, Er, Gr = settle(2.5)
        if abs(Lr - L0) > 6:
            out.append('!! not back after restore: luma %.0f' % Lr)
    flag = ' <==' if any(abs(float(o.split('luma')[1].split()[0]) - L0) > 8 for o in out if 'luma' in o and not o.startswith('!!')) else ''
    print('%d:%02x orig %3d  %s%s' % (SPACE, a, orig, ' | '.join(out), flag), flush=True)
proc.terminate()
