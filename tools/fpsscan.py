#!/usr/bin/env python3
"""Find the firmware's low-light frame-rate switch: log real fps (frames counted per second, in a
thread) together with full dumps of spaces 1/2/3 (read-only), while the light changes.
  fpsscan.py SECONDS OUT.jsonl"""
import json, os, subprocess, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import hpcam  # noqa: E402
from aescan import snapshot  # noqa: E402

secs, out = float(sys.argv[1]), sys.argv[2]
cam = hpcam.Cam(hpcam.find_device())
p = subprocess.Popen(['ffmpeg', '-loglevel', 'quiet', '-f', 'v4l2', '-input_format', 'mjpeg', '-framerate', '30',
                      '-video_size', '640x480', '-i', cam.dev, '-c', 'copy', '-f', 'mjpeg', 'pipe:1'],
                     stdout=subprocess.PIPE)
stamps = []
def reader():
    while True:
        b = os.read(p.stdout.fileno(), 1 << 16)
        if not b:
            return
        t = time.time()
        stamps.extend([t] * b.count(b'\xff\xd9'))
threading.Thread(target=reader, daemon=True).start()
time.sleep(2)
t0 = time.time()
with open(out, 'w') as f:
    while time.time() - t0 < secs:
        ta = time.time()
        regs = snapshot(cam)
        tb = time.time()
        n = sum(1 for s in stamps if ta <= s <= tb)
        fps = n / (tb - ta)
        f.write(json.dumps({'t': round(ta - t0, 1), 'fps': round(fps, 1), 'regs': regs}) + '\n')
        f.flush()
        print('t=%5.1f fps %4.1f' % (ta - t0, fps), flush=True)
p.terminate()
