#!/usr/bin/env python3
"""Build ui/harness.html: the real page with a stub state and a generated test image, so the
ux-ui-agent-skills gates (and anyone) can open it as a static file. Run after editing index.html."""
import json, os, subprocess
UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ui')
STATE = {
    'camera': 'live', 'device': '/dev/video2', 'error': '', 'preview': True, 'virtual': False,
    'loopback': None, 'loopback_name': None, 'service': True, 'balancing': False, 'events': [],
    'profile': {'gains': [64, 64, 70], 'awb': False,
                'uvc': {'brightness': 128, 'contrast': 55, 'gamma': 68, 'saturation': 130, 'hue': 0,
                        'sharpness': 4, 'backlight': 0, 'power_line': 1},
                'virtual': {'denoise': 3.0, 'sharpen': 0.5}},
    'stats': {'fps': 15, 'luma': 112, 'rg': 1.01, 'bg': 0.99,
              'hist': [[int(900 * __import__('math').exp(-((i - c) / 9) ** 2)) + 40 for i in range(48)]
                       for c in (20, 22, 25)]},
}
img = os.path.join(UI, 'harness-test.jpg')
if not os.path.exists(img):
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x480',
                    '-frames:v', '1', '-q:v', '4', '-y', img], check=True)
html = open(os.path.join(UI, 'index.html'), encoding='utf-8').read()
html = html.replace('/ui/', '').replace('__HPCAM_TOKEN__', 'harness')
html = html.replace('<script src="app.js"></script>',
                    '<script>window.HPCAM_STUB = %s;</script>\n  <script src="app.js"></script>'
                    % json.dumps({'state': STATE, 'image': 'harness-test.jpg'}))
html = html.replace('<title>HP Webcam</title>', '<title>HP Webcam (static harness)</title>')
open(os.path.join(UI, 'harness.html'), 'w', encoding='utf-8').write(html)
print('wrote ui/harness.html')
