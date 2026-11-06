"""WCAG contrast of semantic token pairs in ui/tokens.css, dark (base) and light themes."""
import re, sys
css = open(sys.argv[1]).read()
base_block = css.split('@media (prefers-color-scheme: light)')[0]
light_block = re.search(r'prefers-color-scheme: light\)\s*\{\s*:root\s*\{(.*?)\}\s*\}', css, re.S).group(1)
def parse(block):
    return dict(re.findall(r'(--[\w-]+):\s*([^;]+);', block))
base = parse(base_block); light = {**base, **parse(light_block)}
def resolve(t, v):
    for _ in range(5):
        m = re.fullmatch(r'var\((--[\w-]+)\)', v.strip())
        if not m: break
        v = t[m.group(1)]
    return v.strip()
def rgb(h):
    h = h.lstrip('#'); return [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
def lum(c):
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
def ratio(a, b):
    la, lb = sorted([lum(rgb(a)), lum(rgb(b))], reverse=True); return (la + 0.05) / (lb + 0.05)
# (foreground, background, minimum, what)
PAIRS = [
 ('--color-text', '--color-surface', 4.5, 'body text on panel'),
 ('--color-text', '--color-bg', 4.5, 'text on page'),
 ('--color-text-muted', '--color-surface', 4.5, 'hints, group titles'),
 ('--color-text-subtle', '--color-surface', 4.5, 'readout labels (small)'),
 ('--color-text-muted', '--color-surface-sunken', 4.5, 'segmented unselected'),
 ('--color-text', '--color-selected-bg', 4.5, 'segmented selected'),
 ('--color-primary-text', '--color-primary-bg', 4.5, 'primary button'),
 ('--color-primary-text', '--color-primary-bg-hover', 4.5, 'primary button hover'),
 ('--color-primary-text', '--color-primary-bg-active', 4.5, 'primary button active'),
 ('--color-text', '--color-secondary-bg-hover', 4.5, 'secondary hover'),
 ('--color-text', '--color-secondary-bg-active', 4.5, 'secondary active'),
 ('--color-toast-text', '--color-toast-bg', 4.5, 'toast'),
 ('--color-danger-text', '--color-surface', 4.5, 'busy status'),
 ('--color-text', '--color-code-bg', 4.5, 'code'),
 ('--color-border-strong', '--color-surface', 3.0, 'secondary button border (UI)'),
 ('--color-switch-off', '--color-surface', 3.0, 'switch off track (UI)'),
 ('--color-accent', '--color-surface', 3.0, 'switch on track (UI)'),
 ('--color-thumb', '--color-surface', 3.0, 'slider thumb (UI)'),
 ('--color-focus', '--color-surface', 3.0, 'focus ring (UI)'),
 ('--color-focus', '--color-bg', 3.0, 'focus ring on page (UI)'),
 ('--color-text-subtle', '--color-surface', 3.0, 'status dot idle (UI)'),
]
bad = 0
for name, t in (('dark', base), ('light', light)):
    for fg, bg, need, what in PAIRS:
        if fg not in t or bg not in t: print(f'{name:5} MISSING {fg} / {bg}'); bad += 1; continue
        r = ratio(resolve(t, t[fg]), resolve(t, t[bg]))
        ok = r >= need; bad += not ok
        print(f'{name:5} {"pass" if ok else "FAIL"} {r:5.2f} (need {need}) {what}')
print('failures:', bad)
