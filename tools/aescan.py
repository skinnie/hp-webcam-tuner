#!/usr/bin/env python3
"""Read-only register logger for finding the exposure control.

  aescan.py log SECONDS OUT.jsonl [--backlight] [--auto-stop]
                                                  stream, log spaces 1/2/3 + frame luma (~1 Hz)
  aescan.py rank OUT.jsonl                         rank registers by correlation with darkness

Only reads registers (spaces 1, 2, 3). Space 7 and selectors 6/8 are never touched.
--backlight steps the UVC backlight-compensation control 0..5 during the log (restored after).
"""
import json, os, sys, threading, time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import hpcam  # noqa: E402

SPACES = {1: range(0, 256, 4), 2: range(0, 64, 4), 3: range(0, 256, 4)}


def snapshot(cam):
    regs = {}
    for space, starts in SPACES.items():
        for a in starts:
            for i, v in enumerate(cam.read(space, a, 4)):
                regs['%d:%02x' % (space, a + i)] = v
    return regs


def do_log(seconds, out, backlight):
    cam = hpcam.Cam(hpcam.find_device())
    proc = hpcam.ffmpeg_capture(cam.dev)
    luma = {'v': 0.0, 'p95': 0.0}

    def reader():
        while True:
            try:
                f = np.frombuffer(hpcam.read_frame(proc), np.uint8).reshape(hpcam.H, hpcam.W, 3)
            except RuntimeError:
                return
            l = f.mean(axis=2)
            luma['v'], luma['p95'] = float(l.mean()), float(np.percentile(l, 95))
    threading.Thread(target=reader, daemon=True).start()
    bl0 = cam.get_ctrl('backlight')
    time.sleep(3)
    t0 = time.time()
    with open(out, 'w') as f:
        n = 0
        dark_seen_at = None
        while time.time() - t0 < seconds:
            # --auto-stop: end once the lens was covered (luma < 30), 30 s have passed and it is uncovered again
            if '--auto-stop' in sys.argv:
                if luma['v'] < 30 and dark_seen_at is None:
                    dark_seen_at = time.time()
                    print('dark phase detected', flush=True)
                if dark_seen_at and luma["v"] > 60 \
                        and time.time() - dark_seen_at > 30:
                    print('cover + uncover seen, stopping', flush=True)
                    break
            if backlight:
                step = min(5, int((time.time() - t0) / (seconds / 6)))
                cam.set_ctrl('backlight', step)
            row = {'t': round(time.time() - t0, 2), 'luma': luma['v'], 'p95': luma['p95'],
                   'bl': cam.get_ctrl('backlight'), 'regs': snapshot(cam)}
            f.write(json.dumps(row) + '\n')
            f.flush()
            n += 1
            print('t=%5.1f luma=%5.1f samples=%d' % (row['t'], row['luma'], n), flush=True)
    cam.set_ctrl('backlight', bl0)
    proc.terminate()


def do_rank(path, top=25):
    rows = [json.loads(l) for l in open(path)]
    luma = np.array([r['luma'] for r in rows])
    keys = sorted(rows[0]['regs'])
    print('%d samples, luma %.0f..%.0f' % (len(rows), luma.min(), luma.max()))
    series = {k: np.array([r['regs'][k] for r in rows], float) for k in keys}
    # 16-bit little- and big-endian pairs of neighbours
    for k in keys:
        s, a = k.split(':')
        k2 = '%s:%02x' % (s, int(a, 16) + 1)
        if k2 in series:
            series[k + '+LE16'] = series[k] + 256 * series[k2]
            series[k + '+BE16'] = 256 * series[k] + series[k2]
    res = []
    for k, v in series.items():
        if v.std() == 0:
            continue
        c = np.corrcoef(v, luma)[0, 1]
        res.append((abs(c), c, k, v.min(), v.max(), len(set(v))))
    res.sort(reverse=True)
    print('corr    register        min    max  distinct')
    for _, c, k, lo, hi, nd in res[:top]:
        print('%+.3f  %-14s %6.0f %6.0f %5d' % (c, k, lo, hi, nd))


if __name__ == '__main__':
    if sys.argv[1] == 'log':
        do_log(float(sys.argv[2]), sys.argv[3], '--backlight' in sys.argv)
    else:
        do_rank(sys.argv[2])
