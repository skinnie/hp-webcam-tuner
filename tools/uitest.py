"""Drive the HP Webcam UI in an off-screen WebKit view and assert behaviour."""
import sys, json, time, urllib.request, gi
gi.require_version('Gtk','3.0'); gi.require_version('WebKit2','4.1')
from gi.repository import Gtk, WebKit2, GLib
URL, W, H = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
win = Gtk.OffscreenWindow(); wv = WebKit2.WebView(); wv.set_size_request(W, H); win.add(wv); win.show_all()
results = []
def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        Gtk.main_iteration_do(False); time.sleep(0.005)
def js(code):
    box = {}
    def done(v, res, _):
        try: box['v'] = v.evaluate_javascript_finish(res).to_json(0)
        except Exception as e: box['v'] = json.dumps({'jserror': str(e)})
    wv.evaluate_javascript('JSON.stringify((() => {' + code + '})())', -1, None, None, None, done, None)
    while 'v' not in box: Gtk.main_iteration_do(True)
    return json.loads(json.loads(box['v'])) if box['v'] not in (None, 'null', 'undefined') else None
def server():
    tok = js("return document.querySelector('meta[name=hpcam-token]').content")
    req = urllib.request.Request(URL + 'api/state', headers={'X-HPCam-Token': tok})
    return json.load(urllib.request.urlopen(req))
def check(name, ok, detail=''):
    results.append(ok); print(('pass ' if ok else 'FAIL ') + name + (('  ' + str(detail)) if detail else ''), flush=True)
wv.load_uri(URL); pump(5)

if '--layout' in sys.argv:
    r = js("return {sw: document.documentElement.scrollWidth, iw: innerWidth}")
    check('no horizontal overflow at %dpx' % W, r['sw'] <= r['iw'], r)
    clipped = js("""return [...document.querySelectorAll('button,label,output,.field-hint,h1,h2,dd,dt')].filter(e => e.offsetParent && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflow !== 'visible' && !e.closest('.status-chip') && !e.classList.contains('sr-only')).map(e => e.id || e.className || e.textContent.slice(0,20))""")
    check('no clipped text at %dpx' % W, not clipped, clipped)
    sys.exit(0 if all(results) else 1)

# accessible names + target size for every interactive element
rep = js("""
const els = [...document.querySelectorAll('button, input, [role=switch], [role=radio], a[href]')].filter(e => e.offsetParent !== null);
const name = (e) => e.getAttribute('aria-label') || (e.getAttribute('aria-labelledby') || '').split(' ').map(i => document.getElementById(i)?.textContent || '').join(' ').trim()
  || (e.id && document.querySelector('label[for="' + e.id + '"]')?.textContent) || e.textContent.trim();
return els.map(e => { const r = e.getBoundingClientRect(); return {id: e.id || e.dataset.value || e.dataset.action || e.className, name: name(e), w: r.width, h: r.height, tab: e.tabIndex}; });
""")
unnamed = [e['id'] for e in rep if not e['name']]
check('every control has an accessible name (%d controls)' % len(rep), not unnamed, unnamed)
small = [(e['id'], round(e['w']), round(e['h'])) for e in rep if e['w'] < 24 or e['h'] < 24]
check('every target is at least 24x24', not small, small)
untab = [e['id'] for e in rep if e['tab'] < 0 and 'radio' not in str(e) and e['id'] not in ('0','2')]
check('controls reachable by Tab (radio group uses roving tabindex)', not untab, untab)

# switch: AWB
before = server()['profile']['awb']
js("document.getElementById('sw-awb').click()"); pump(1.5)
a = js("return document.getElementById('sw-awb').getAttribute('aria-checked')")
s = server()['profile']['awb']
check('AWB switch toggles aria-checked and server state', a == str(not before).lower() and s == (not before), (a, s))
dis = js("return document.getElementById('s-gain_r').disabled")
check('gain sliders disabled while AWB is on', dis == (not before), dis)
js("document.getElementById('sw-awb').click()"); pump(1.5)
check('AWB switch toggles back', server()['profile']['awb'] == before)

# slider: change contrast through the input event path
old = server()['profile']['uvc']['contrast']
js("const i=document.getElementById('s-contrast'); i.value=%d; i.dispatchEvent(new Event('input'))" % (old + 5)); pump(1.2)
new = server()['profile']['uvc']['contrast']
out = js("return document.getElementById('s-contrast-out').textContent")
check('contrast slider updates readout and camera', new == old + 5 and out == str(old + 5), (old, new, out))
js("const i=document.getElementById('s-contrast'); i.value=%d; i.dispatchEvent(new Event('input'))" % old); pump(1.2)

# radio group: arrow key moves selection
js("document.querySelector('#flicker [aria-checked=true]').focus()")
cur = server()['profile']['uvc']['power_line']
js("document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true}))"); pump(1)
nxt = server()['profile']['uvc']['power_line']
foc = js("return document.activeElement.dataset.value")
check('flicker radio group: ArrowRight selects and focuses next', nxt == (cur + 1) % 3 and foc == str(nxt), (cur, nxt, foc))
js("[...document.querySelectorAll('#flicker [role=radio]')].find(r => r.dataset.value=='%d').click()" % cur); pump(1)
check('flicker restored by click', server()['profile']['uvc']['power_line'] == cur)

# menu: opens, focus moves in, Escape closes and returns focus
js("document.getElementById('btn-menu').click()"); pump(0.3)
m = js("return {open: !document.getElementById('menu').hidden, exp: document.getElementById('btn-menu').getAttribute('aria-expanded'), inside: !!document.activeElement.closest('#menu')}")
check('menu opens with focus inside', m == {'open': True, 'exp': 'true', 'inside': True}, m)
js("document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))"); pump(0.3)
m = js("return {open: !document.getElementById('menu').hidden, back: document.activeElement.id}")
check('Escape closes menu and returns focus', m == {'open': False, 'back': 'btn-menu'}, m)

# preview pause / resume
js("document.getElementById('btn-preview').click()"); pump(2.5)
st = server(); ph = js("return document.getElementById('placeholder-title').textContent")
check('pause preview frees the camera', st['camera'] == 'paused' and 'paused' in ph.lower(), (st['camera'], ph))
js("document.getElementById('btn-preview').click()"); pump(4)
check('resume preview goes live again', server()['camera'] == 'live', server()['camera'])

# photo
import os, glob
pdir = os.path.expanduser('~/Pictures/HP Webcam')
n0 = len(glob.glob(pdir + '/*.jpg'))
js("document.getElementById('btn-photo').click()"); pump(1.5)
files = sorted(glob.glob(pdir + '/*.jpg'))
toast = js("return [...document.querySelectorAll('.toast')].map(t => t.textContent)")
check('Take photo saves a JPEG and announces it', len(files) == n0 + 1 and any('Photo saved' in t for t in toast), (len(files) - n0, toast))
if len(files) == n0 + 1: os.remove(files[-1])

# balance once: start from a wrong blue gain, expect busy, then gains pulled back toward neutral
js("const i=document.getElementById('s-gain_b'); i.value=1.4; i.dispatchEvent(new Event('input'))"); pump(2.5)
wrong = server()['profile']['gains'][2]
js("document.getElementById('btn-balance').click()"); pump(0.8)
busy = js("return document.getElementById('btn-balance').getAttribute('aria-busy')")
pump(6)
done = js("return document.getElementById('btn-balance').getAttribute('aria-busy')")
fixed = server()['profile']['gains'][2]
check('Balance once shows busy, then finishes', busy == 'true' and done == 'false', (busy, done))
check('Balance once pulls a wrong blue gain back', abs(fixed - 64) < abs(wrong - 64), (wrong, fixed))
print('%d/%d passed' % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
