'use strict';
/* HP Webcam tuner front end. Talks to hpcam_web.py on localhost. */

const TOKEN = document.querySelector('meta[name="hpcam-token"]').content;
// Static harness (ui/harness.html, used by the design gates): a stub state, no server.
const STUB = window.HPCAM_STUB || null;
const $ = (id) => document.getElementById(id);

const PICTURE = [
  { key: 'brightness', label: 'Brightness', min: 0, max: 255, step: 1, def: 128 },
  { key: 'contrast', label: 'Contrast', min: 0, max: 100, step: 1, def: 25 },
  { key: 'gamma', label: 'Gamma', hint: 'Lower is brighter', min: 40, max: 100, step: 1, def: 75 },
  { key: 'saturation', label: 'Saturation', min: 0, max: 200, step: 1, def: 155 },
  { key: 'hue', label: 'Hue', min: -180, max: 180, step: 1, def: 0, fmt: (v) => `${v}°` },
  { key: 'sharpness', label: 'Sharpness', min: 0, max: 10, step: 1, def: 6 },
  { key: 'backlight', label: 'Backlight compensation', hint: 'Brightens faces against a bright window', min: 0, max: 5, step: 1, def: 0 },
];
const GAINS = [
  { key: 'gain_r', label: 'Red gain', min: 0.25, max: 3.98, step: 0.01, def: 1, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'gain_g', label: 'Green gain', min: 0.25, max: 3.98, step: 0.01, def: 1, fmt: (v) => `${v.toFixed(2)}x` },
  { key: 'gain_b', label: 'Blue gain', min: 0.25, max: 3.98, step: 0.01, def: 1, fmt: (v) => `${v.toFixed(2)}x` },
];
const VIRTUAL = [
  { key: 'denoise', label: 'Noise reduction', min: 0, max: 8, step: 0.5, def: 3, fmt: (v) => v.toFixed(1) },
  { key: 'sharpen', label: 'Extra sharpening', min: 0, max: 1.5, step: 0.05, def: 0.5, fmt: (v) => v.toFixed(2) },
];

const sliders = {};
let state = null;
let lastEvent = -1;   // -1 until the first state arrives: old events are not replayed
let balanceUntil = 0;

/* ---------- API ---------- */
async function api(path, body) {
  if (STUB) return true;
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-HPCam-Token': TOKEN },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ ok: false, error: 'No answer from the camera service' }));
  if (!data.ok) toast(data.error || 'That did not work');
  return data.ok;
}
const setValue = (key, value) => api('/api/set', { key, value });
const action = (name) => api('/api/action', { name });

/* ---------- sliders ---------- */
function makeSlider(container, spec) {
  const id = `s-${spec.key}`;
  const field = document.createElement('div');
  field.className = 'field';
  const fmt = spec.fmt || ((v) => String(Math.round(v)));
  field.innerHTML = `
    <div class="field-head">
      <label class="field-label" for="${id}">${spec.label}</label>
      <output class="field-value" for="${id}" id="${id}-out"></output>
    </div>
    <input class="range" type="range" id="${id}" min="${spec.min}" max="${spec.max}" step="${spec.step}">
    ${spec.hint ? `<p class="field-hint">${spec.hint}</p>` : ''}`;
  container.appendChild(field);
  const input = field.querySelector('input');
  const out = field.querySelector('output');
  let timer = 0;
  let dragging = false;
  const paint = (v) => {
    const pct = ((v - spec.min) / (spec.max - spec.min)) * 100;
    input.style.setProperty('--fill', `${pct}%`);
    out.textContent = fmt(v);
    input.setAttribute('aria-valuetext', fmt(v));
  };
  input.addEventListener('input', () => {
    const v = Number(input.value);
    paint(v);
    clearTimeout(timer);
    timer = setTimeout(() => setValue(spec.key, v), 60);
  });
  input.addEventListener('pointerdown', () => { dragging = true; });
  window.addEventListener('pointerup', () => { dragging = false; });
  // double-click the label to return to the camera's default
  field.querySelector('label').addEventListener('dblclick', () => {
    input.value = spec.def;
    input.dispatchEvent(new Event('input'));
  });
  sliders[spec.key] = {
    field, input,
    set(v) {
      if (dragging || document.activeElement === input) return;
      input.value = v;
      paint(Number(input.value));
    },
    enable(on) {
      input.disabled = !on;
      field.setAttribute('aria-disabled', on ? 'false' : 'true');
    },
  };
}

PICTURE.forEach((s) => makeSlider($('picture-fields'), s));
GAINS.forEach((s) => makeSlider($('gain-fields'), s));
VIRTUAL.forEach((s) => makeSlider($('virtual-fields'), s));

/* ---------- switches ---------- */
const KNOB = `<span class="knob" aria-hidden="true">
  <svg class="mark-off" viewBox="0 0 24 24"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
  <svg class="mark-on" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg></span>`;
document.querySelectorAll('.switch').forEach((sw) => { sw.innerHTML = KNOB; });

function bindSwitch(sw, onChange) {
  sw.addEventListener('click', async () => {
    if (sw.getAttribute('aria-disabled') === 'true') {
      toast(sw.dataset.disabledReason || 'Not available right now');
      return;
    }
    const next = sw.getAttribute('aria-checked') !== 'true';
    sw.setAttribute('aria-checked', String(next));
    sw.dataset.pending = '1';
    const ok = await onChange(next);
    delete sw.dataset.pending;
    if (!ok) sw.setAttribute('aria-checked', String(!next));
  });
}
function showSwitch(sw, on) {
  if (!sw.dataset.pending) sw.setAttribute('aria-checked', String(!!on));
}

bindSwitch($('sw-awb'), (on) => setValue('awb', on));
bindSwitch($('sw-hist'), (on) => setValue('histogram', on));
bindSwitch($('sw-virtual'), (on) => action(on ? 'virtual_on' : 'virtual_off'));
bindSwitch($('sw-service'), (on) => action(on ? 'service_on' : 'service_off'));

/* ---------- flicker radio group (arrow keys move selection) ---------- */
const flicker = $('flicker');
const radios = [...flicker.querySelectorAll('[role="radio"]')];
function selectFlicker(value, send) {
  radios.forEach((r) => {
    const on = r.dataset.value === String(value);
    r.setAttribute('aria-checked', String(on));
    r.tabIndex = on ? 0 : -1;
  });
  if (send) setValue('power_line', Number(value));
}
radios.forEach((r, i) => {
  r.addEventListener('click', () => selectFlicker(r.dataset.value, true));
  r.addEventListener('keydown', (e) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!step) return;
    e.preventDefault();
    const next = radios[(i + step + radios.length) % radios.length];
    selectFlicker(next.dataset.value, true);
    next.focus();
  });
});

/* ---------- header actions ---------- */
$('btn-photo').addEventListener('click', () => action('snapshot'));
$('btn-preview').addEventListener('click', () => {
  const on = $('btn-preview').getAttribute('aria-pressed') !== 'true';
  action(on ? 'preview_on' : 'preview_off');
  showPreviewButton(on);
});
function showPreviewButton(on) {
  const b = $('btn-preview');
  b.setAttribute('aria-pressed', String(on));
  b.setAttribute('aria-label', on ? 'Pause preview' : 'Resume preview');
  b.title = on ? 'Pause preview so other apps can use the camera' : 'Resume preview';
  $('preview-icon').setAttribute('href', on ? '#i-pause' : '#i-play');
}

const menuBtn = $('btn-menu');
const menu = $('menu');
function openMenu(open) {
  menu.hidden = !open;
  menuBtn.setAttribute('aria-expanded', String(open));
  if (open) menu.querySelector('button').focus();
}
menuBtn.addEventListener('click', () => openMenu(menu.hidden));
menu.addEventListener('keydown', (e) => {
  const items = [...menu.querySelectorAll('button')];
  const i = items.indexOf(document.activeElement);
  if (e.key === 'Escape') { openMenu(false); menuBtn.focus(); }
  if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length].focus(); }
  if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
});
document.addEventListener('click', (e) => {
  if (!menu.hidden && !e.target.closest('.menu-wrap')) openMenu(false);
});
menu.querySelectorAll('[data-action]').forEach((b) => b.addEventListener('click', () => {
  openMenu(false);
  menuBtn.focus();
  action(b.dataset.action);
}));

$('btn-balance').addEventListener('click', () => {
  balanceUntil = Date.now() + 1200;   // keep the busy state visible even when it finishes at once
  const b = $('btn-balance');
  b.setAttribute('aria-busy', 'true');
  b.querySelector('.btn-label').textContent = 'Balancing';
  action('balance');
});

/* ---------- toasts ---------- */
function toast(text) {
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = text;
  $('toasts').appendChild(t);
  setTimeout(() => t.remove(), 3200);
}

/* ---------- preview ---------- */
const img = $('preview');
let streamOn = false;
function setStream(on) {
  if (on === streamOn) return;
  streamOn = on;
  if (on) {
    img.src = STUB ? STUB.image : `/stream.mjpg?t=${encodeURIComponent(TOKEN)}&n=${Date.now()}`;
  } else {
    img.removeAttribute('src');
  }
}
img.addEventListener('error', () => { streamOn = false; });

const PLACEHOLDER = {
  absent: ['Plug in the HP USB Webcam', 'Settings are applied as soon as it shows up.', 'plug'],
  starting: ['Starting the camera', '', 'spin'],
  busy: ['The camera is in use by another app', 'Close that app, or use the virtual camera so both can share it.', 'plug'],
  paused: ['Preview paused', 'Other apps can use the camera now. Your settings stay applied.', 'none'],
};
const STATUS = {
  absent: 'Not connected', starting: 'Starting', live: 'Live', busy: 'In use by another app', paused: 'Preview paused',
};

function render(s) {
  state = s;
  const cam = s.camera;
  $('status-chip').dataset.state = cam;
  $('status-text').textContent = cam === 'live' && s.virtual ? 'Live, shared as virtual camera' : STATUS[cam];
  setStream(cam === 'live' || cam === 'starting');
  const live = cam === 'live';
  img.hidden = !live;
  $('placeholder').hidden = live;
  if (!live) {
    const [title, body, kind] = PLACEHOLDER[cam] || PLACEHOLDER.starting;
    $('placeholder-title').textContent = title;
    $('placeholder-body').textContent = body;
    $('spinner').hidden = kind !== 'spin';
    $('placeholder-icon').hidden = kind !== 'plug';
  }
  $('btn-photo').disabled = !live;
  showPreviewButton(s.preview);

  const p = s.profile;
  PICTURE.forEach((spec) => sliders[spec.key].set(p.uvc[spec.key] ?? spec.def));
  GAINS.forEach((spec, i) => sliders[spec.key].set(p.gains[i] / 64));
  GAINS.forEach((spec) => sliders[spec.key].enable(!p.awb));
  $('gain-hint').textContent = p.awb
    ? 'Automatic white balance is adjusting these gains for you.'
    : 'The camera has no white balance of its own. These are its hidden colour gains.';
  VIRTUAL.forEach((spec) => { sliders[spec.key].set(p.virtual[spec.key]); sliders[spec.key].enable(!!s.loopback); });
  selectFlicker(p.uvc.power_line ?? 1, false);
  showSwitch($('sw-awb'), p.awb);
  showSwitch($('sw-hist'), p.histogram);
  $('hist-figure').hidden = !p.histogram;
  $('wb-readout').hidden = !s.measuring;
  showSwitch($('sw-virtual'), s.virtual);
  showSwitch($('sw-service'), s.service);

  const bal = $('btn-balance');
  const balancing = !!s.balancing || Date.now() < balanceUntil;
  bal.setAttribute('aria-busy', String(balancing));
  bal.disabled = !live || p.awb;
  bal.querySelector('.btn-label').textContent = balancing ? 'Balancing' : 'Balance once on what the camera sees';

  const vsw = $('sw-virtual');
  if (s.loopback) {
    vsw.setAttribute('aria-disabled', 'false');
    $('virt-hint').textContent = `Apps see it as "${s.loopback_name}". Pick it in your video call app.`;
  } else {
    vsw.setAttribute('aria-disabled', 'true');
    vsw.dataset.disabledReason = 'Load the virtual camera module first (see the command below)';
    $('virt-hint').innerHTML = 'Needs the v4l2loopback module, loaded once per boot:'
      + '<code>sudo modprobe v4l2loopback card_label="HP Webcam (tuned)" exclusive_caps=1</code>';
  }

  const st = s.stats;
  $('r-fps').textContent = live ? st.fps.toFixed(0) : '0';
  $('lowlight').hidden = !(live && st.fps > 0 && st.fps < 9);
  $('r-luma').textContent = live ? Math.round(st.luma) : '0';
  if (live) {
    const off = Math.max(Math.abs(st.rg - 1), Math.abs(st.bg - 1));
    let verdict = 'Neutral';
    if (off > 0.03) {
      const warm = st.rg - st.bg;
      verdict = warm > 0.03 ? 'Too warm' : warm < -0.03 ? 'Too cool' : (st.rg + st.bg) / 2 < 1 ? 'Green tint' : 'Magenta tint';
    }
    $('r-wb').textContent = verdict;
    $('hist-caption').textContent = `Histogram. Average brightness ${Math.round(st.luma)} of 255. White balance ${verdict.toLowerCase()}.`;
    if (p.histogram) drawHist(st.hist);
  } else {
    $('r-wb').textContent = 'No picture';
    drawHist(null);
  }

  if (lastEvent < 0) {
    lastEvent = s.events.length ? s.events[s.events.length - 1][0] : 0;
  }
  for (const [seq, text] of s.events) {
    if (seq > lastEvent) {
      toast(text);
      lastEvent = seq;
    }
  }
}

/* ---------- histogram ---------- */
const canvas = $('hist');
const css = getComputedStyle(document.documentElement);
const VIZ = ['--viz-red', '--viz-green', '--viz-blue'].map((v) => css.getPropertyValue(v).trim());
function drawHist(hist) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!hist) return;
  const peak = Math.max(1, ...hist.flat());
  hist.forEach((bins, c) => {
    ctx.beginPath();
    ctx.moveTo(0, h);
    bins.forEach((v, i) => ctx.lineTo((i / (bins.length - 1)) * w, h - (v / peak) * (h - 4)));
    ctx.lineTo(w, h);
    ctx.closePath();
    ctx.globalAlpha = 0.45;
    ctx.fillStyle = VIZ[c];
    ctx.fill();
  });
  ctx.globalAlpha = 1;
}

/* ---------- live state ---------- */
function connect() {
  if (STUB) { render(STUB.state); return; }
  const es = new EventSource(`/events?t=${encodeURIComponent(TOKEN)}`);
  es.onmessage = (e) => render(JSON.parse(e.data));
  es.onerror = () => {
    es.close();
    $('status-chip').dataset.state = 'busy';
    $('status-text').textContent = 'Lost contact with the camera service';
    setTimeout(connect, 2000);
  };
}
connect();
