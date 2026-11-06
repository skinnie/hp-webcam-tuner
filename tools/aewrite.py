#!/usr/bin/env python3
"""Stage-2 exposure search: write one candidate register at a time, watch frame luma and the
register's own readback for 2 s, then restore the original. Spaces 1 and 2 only."""
import os, sys, threading, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import hpcam  # noqa: E402

CANDIDATES = [(1, 0x55), (1, 0x56), (1, 0x57), (1, 0x58), (1, 0xbd), (1, 0xbe), (1, 0xc2), (1, 0xc3),
              (1, 0xb2), (1, 0xb3), (2, 0x32), (2, 0x34), (2, 0x38), (2, 0x39)]

cam = hpcam.Cam(hpcam.find_device())
proc = hpcam.ffmpeg_capture(cam.dev)
luma = {'v': 0.0}
def reader():
    while True:
        try:
            f = np.frombuffer(hpcam.read_frame(proc), np.uint8)
        except RuntimeError:
            return
        luma['v'] = float(f.mean())
threading.Thread(target=reader, daemon=True).start()
time.sleep(4)

def watch(space, addr, secs=2.0):
    out = []
    t = time.time()
    while time.time() - t < secs:
        out.append((round(luma['v']), cam.read(space, addr)[0]))
        time.sleep(0.25)
    return out

cands = CANDIDATES if len(sys.argv) < 2 else [tuple(int(x, 0) for x in a.split(':')) for a in sys.argv[1:]]
for space, addr in cands:
    orig = cam.read(space, addr)[0]
    base = watch(space, addr, 1.0)
    for val in (max(0, orig // 3), min(255, orig * 2 + 20)):
        cam.write(space, addr, val)
        res = watch(space, addr)
        cam.write(space, addr, orig)
        time.sleep(1.2)
        lum = [l for l, _ in res]
        held = sum(1 for _, r in res if r == val)
        print('%d:%02x orig %3d -> %3d  luma %3d -> %3d..%3d  readback held %d/%d  %s'
              % (space, addr, orig, val, base[-1][0], min(lum), max(lum), held, len(res),
                 ' '.join(str(r) for _, r in res)), flush=True)
proc.terminate()
