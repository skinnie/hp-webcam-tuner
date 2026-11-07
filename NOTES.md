# HP USB Webcam (AU165AA, USB 03f0:8007): notes

## Hardware
- Vimicro UVC 1.0 bridge (HP project name "HP Panda"). VGA max (640x480), YUYV + MJPEG.
- Linux: stock `uvcvideo`, shows up as /dev/video2 (+ metadata node /dev/video3).
- YUYV at any rate fails with ENOSPC: camera always asks for max iso bandwidth.
  Fix candidate: `modprobe uvcvideo quirks=0x80` (UVC_QUIRK_FIX_BANDWIDTH), needs root, untested.
- No auto-exposure / gain / AWB controls exposed. Only brightness, contrast, saturation, hue,
  gamma, WB temperature (manual), sharpness, backlight comp, power-line freq, zoom.

## Install disc (HPAU165AA/HP Webcam.iso)
- No camera driver (uses Windows' UVC class driver). Contents: HP Button Manager (BM.exe),
  ArcSoft WebCam Companion 3, ArcSoft Magic-i 2 (+ generic ArcSoft KS upper-filter, effects only),
  Vimicro `exvmuvc.ax` (generic XU passthrough proxy, no register map).
- Only device ID referenced by camera-specific code: vid_03f0&pid_8007.
  `VID_145F&PID_0164` in the Button Manager installer string tables is a leftover from another model.
- Ghidra decompiles in `re/` (BM.exe, DSDLL.dll, exvmuvc.ax); kept local, not published (HP code).

## Vendor extension unit (unit 4, GUID d13577f0-8d89-4700-812e-7dd5e2fdb898)
Decoded from BM.exe/DSDLL.dll (HP Button Manager) + experiments. All 4-byte except 7/8 (10 bytes).
- **sel 5 = address/length register**: SET `[addr, len(1-4), x, x]` (bytes 2/3 ignored).
  GET: status, byte3 == 1 while the snapshot button is pressed.
- **sel 1, 2, 3, 7 = four separate 256-byte spaces**, read at the sel-5 address (`len` bytes).
  GET stalls/babbles until sel 5 has been set once.
- Write: sel5 SET `[addr,1,0,0]`, GET selN, SET selN `[addr, value, 1, keep_byte3]` (BM.exe sequence).
  Verified for spaces 1 and 3. Space 7 never written (looks like a settings table, may be flash).
- sel 4: returns 0xff per `len` byte (probably a write mask). sel 6/8: GET times out (unknown, not touched).
- While idle, reads return the active value and writes take effect when streaming starts.
  Writes persist across stream stop/start until unplug.

## Register map (diffing dumps while changing UVC controls: tools/mapctl.py, map4)
| space:reg | meaning |
|---|---|
| 3:04 / 3:05 / 3:06 | **G / R / B** gain, 0x40 = 1.0 (measured by output colour). WB-temperature control only writes 3:06. No AWB in firmware. |
| 3:07-09 | colour offsets (brightness control) |
| 3:18-21 | fixed curve 30 49 5d .. eb (not touched by controls) |
| 3:5B-73 | 5x5 luma grid (AE stats); 3:5F mean luma |
| 3:74-83 | four 32-bit BE accumulators, pre-gain (do not react to gains: useless for AWB) |
| 3:E1 | GPIO, bit4 = LED |
| 1:17-28 | 3x3 colour matrix (11-bit signed pairs), written by saturation + hue |
| 1:A2-AB | tone curve, written by contrast + gamma (lower gamma number = brighter) |
| 1:B6 | sharpness |
| 1:56 (= 3:84) | AE-derived level, firmware recomputes it; writing has no lasting effect |
| 2:32/34/38-39 | jitter every read; not exposure (write overwritten at once) |
| 7:xx | defaults table: tone curve copy, 640, 5000 K, 500/1000 limits |

Not found: sensor exposure/gain/AE target. Backlight compensation is the only lever on AE target.
The sensor is probably behind sel 6/8 (I2C?), unprobed because a wrong SET could hit flash.

## Tool: hpcam.py (no root)
- `./hpcam.py calibrate` - grey-world AWB on near-neutral pixels, iterates chip gains, saves
  ~/.config/hpcam/profile.json
- `./hpcam.py apply` / `run` (re-applies on replug, restores gains if an app moves the WB slider)
- `./hpcam.py virtual` - owns the camera, live AWB + hqdn3d + unsharp into v4l2loopback.
  Needs once: `sudo modprobe v4l2loopback card_label="HP Webcam (tuned)" exclusive_caps=1`
- `./hpcam.py status`, `reset`
Profile default: contrast 55, gamma 68, saturation 130, sharpness 4 (chosen from test shots).
In the test room the scene was already neutral at gains 1.0, so AWB matters mainly under other light.

## GUI: hpcam_gui.py (GTK 3)
Live preview + RGB histogram, picture sliders, hidden R/G/B gains with continuous auto white balance
and a "balance once" button, photo button (camera's physical snapshot button works too, saved to
~/Pictures/HP Webcam), virtual-camera switch with noise reduction / sharpening, and a switch that
installs `hpcam.py run` as a systemd user service. Changes auto-save to ~/.config/hpcam/profile.json.
Launcher: ~/.local/share/applications/hpcam.desktop. Off-screen test: `hpcam_gui.py --screenshot out.png`.
All processes take a flock ($XDG_RUNTIME_DIR/hpcam.lock) around each register access.

Chip state is lost on replug: the chip reads all zeros until its first stream, then comes up with
factory values. `run` and the GUI re-apply the profile once the chip is live (ensure_profile).

## App: web UI in a native window (launcher target since 2026-11-06)
- `hpcam_app.py` opens a GTK window with WebKitGTK 4.1 showing `ui/`; `--browser` opens it in the browser.
- `hpcam_web.py` = controller + server on 127.0.0.1 (random port). API, stream and events need the
  per-run token from the page (403 otherwise). One ffmpeg: MJPEG preview on stdout, 80x60 RGB stats
  on a second pipe (histogram, AWB), optional processed copy into v4l2loopback. Photos saved as JPEG.
- `ui/`: tokens.css (the only place with colours/sizes/timings, dark + light), app.css, app.js,
  index.html, CREDITS.md (Uiverse Galaxy: switch, slider, button, spinner; ux-ui-agent-skills rules).
- Checks run with own scripts (running the kit's Node gates was not permitted): token-pair contrast
  in both themes 0 failures; no hex/px/ms outside tokens, no emoji or dashes, no native select;
  16/16 interaction tests in an off-screen WebKit view; no overflow or clipped text 280-1280px.
- hpcam_gui.py (GTK 3) still works but is no longer the launcher target.

## Exposure investigation (2026-11-06, tools/aescan.py, aewrite.py, aetarget.py, aehold.py, aecap.py)
- 1:56-57 (16-bit LE) = exposure, 1:58 = gain, both driven by the firmware AE loop: writes take
  effect (1:57=0 dropped luma 83 -> 62) but are walked back within ~2 s.
- Backlight compensation moves 1:56 up / 1:58 down and rewrites the tone curve 1:A3-AB, 1:BE, 1:C3.
- 1:13 = digital brightness multiplier after the sensor (2 -> 4: luma 83 -> 110, exposure unchanged).
- No AE target, limit or enable found in space 1 (0x00-0x16, 0x40-0x5B) or space 2 static bytes.
- Holding an exposure cap by rewriting every 100 ms: steady at about half exposure, flickers at a
  quarter; frame rate barely improves. Not shipped.
- Low light: the camera lowers its own frame rate (wall-clock 3.9 fps at 50 Hz, 4.8 fps at 60 Hz or
  off, in evening room light; about 15 fps in daylight). Requested frame rate and size make no
  difference. 3:28 and 1:B5/1:C3/1:B6 change with light but writing them does not change frame rate.
  (The "~15 fps in daylight" figure above was never measured properly; see the frame-rate section.)
  Frame timing is most likely inside the sensor (I2C, behind unprobed sel 6/8). Fix is more light.
- Measurement pitfall: ffmpeg's fps counter and fps-filtered pipes duplicate frames; count JPEG
  frames against wall-clock time instead.

## Uncompressed video and virtual camera (tested 2026-11-06 after setup-root.sh)
- uvcvideo quirks=0x80: YUYV 640x480 no longer ENOSPC but delivers 0 frames at 30/15/10/5 fps;
  352x288 and 320x240 YUYV deliver frames. Not useful; quirk removed from setup-root.sh.
- Virtual camera: app "Send to other apps" -> /dev/video10 "HP Webcam (tuned)" readable by another
  process (ffmpeg as a stand-in for a call app), switching off frees it.
- Frame-rate readout bug (fixed): the preview pipeline used an fps=15 filter, which padded the
  stream with duplicate frames, so the app said 15 fps while showing ~4.5. Preview now passes the
  camera's frames through (-fps_mode passthrough) and the UI shows a low-light hint below 9 fps.
- Fair comparison, real frames counted by wall clock (evening light): stock settings without app,
  our profile without app, and profile + the app's button polling all give 5-6.5 fps. The app does
  not slow the camera; the camera's own low-light mode does.
- Latency fix: the preview now copies the camera's own JPEGs (they include Huffman tables) instead
  of decode + re-encode, with -fflags nobuffer -flags low_delay -threads 1. Measured by flipping the
  brightness control and timing the change in received frames: median 522 ms -> 334 ms. The rest is
  the camera (one frame is ~200 ms at ~5 fps in dim light). With the virtual camera on, the preview
  is still the processed (re-encoded) picture.
- Histogram is now optional (off by default). With histogram and automatic white balance off, the
  app decodes nothing: ffmpeg only copies JPEGs (0.1% of a core vs 2.3% with statistics at ~5 fps).
  Frame rate then comes from frames received, brightness from the chip's meter (3:5F, its own scale).
- Same room, same moment, both streaming (2026-11-06 evening): Creative VF0260 with our patched
  ov519 driver ~30 fps, HP 6.6 fps. The difference is sensor control, not light alone.

## Frame rate: the low-light mode (measured 2026-11-06, tools/fpsscan.py, frames counted per second)
- Negotiation is fine: the camera advertises 1/30 s for every MJPEG size, VIDIOC_G_PARM after
  streamon reports 1/30 s.
- Pointed at a bright lamp: 29-31 fps; back to the room: 4-7 fps within a second or two. The
  switch is a firmware/sensor decision.
- No register in spaces 1/2/3 splits cleanly between the fast and slow states (1:56, 1:BE, 1:58
  overlap). Colour gains x2/x4 and 1:13 do not move the AE's own brightness measure (it is taken
  before them), so they cannot trick the AE into the fast mode.
- Selector 6 is write-only (GET always times out after 5 s); a flash-safe write [4B FF 01 00]
  changed nothing visible. Per the VC0345 datasheet the sensor and the settings EEPROM share one
  I2C bus, so blind selector 6/8 writes could alter the EEPROM (USB IDs, firmware patch). Not
  pursued without the sensor model.

## Space 7 fully decoded (read-only, tools/data/space7.json) — it is the power-on defaults table
Selector 7 is 10 bytes wide per address but only byte 0 is used; bytes 1-9 are always zero.
Addresses 0x00-0xa4 hold a static table (same every read), 0xa5-0xff are zero. Decoded landmarks:
- 0x64-65 = 0x0280 = 640 (default frame width)
- 0x68-69 = 0x1388 = 5000 (white-balance temperature default, 5000K — matches the UVC control default)
- 0x47-48 = 500, 0x49-4a = 1000 (the AE limits seen elsewhere)
- 0x70-7a = 1e 30 49 5d 6f 7f 8d a8 c0 d7 eb (the gamma/tone curve, also in space 3 at 0x18)
It is the firmware's default ISP/UVC settings, NOT a sensor I2C init script: it holds UVC-level
concepts (WB in Kelvin, frame width) rather than sensor address/value pairs, and contains no sensor
part number or USB VID/PID. So space 7 does not identify the sensor.

## Where the sensor identity actually lives (not reachable read-only)
Per the VC0345 datasheet the sensor init and any firmware patch live in the chip's OTP ROM / external
EEPROM, reached over the chip's internal I2C bus. That bus is what selector 6 writes to (and selector
6/8 never answer reads). There is no path through this XU interface to read the sensor's ID registers
or the EEPROM without blind writes on the shared sensor/EEPROM bus. Identifying the sensor needs the
chip marking from opening the case.

## Portability test on a second machine (2026-11-07) — Linux Mint 22.1, kernel 6.8.0-149
Tested over SSH on skinnie@100.113.100.37 (Ubuntu 24.04 base, Python 3.12, no GUI session):
- git clone of the public repo, all modules import; find_device() returns None cleanly with no camera.
- Web server boots headless; token auth works (unauth /api/state -> 403); camera=absent handled.
- With the HP camera plugged in (enumerates as /dev/video1, uvcvideo): the vendor extension-unit
  protocol works -> `hpcam status` reads the controls; after a 3 s stream the registers populate
  (tone curve, gains) exactly as locally; UVC controls reflect the applied profile.
- `hpcam calibrate` ran a full live white balance and converged (R/G 0.99, B/G 1.01), saved profile.
- Web backend: camera=live, MJPEG stream serves real frames (~3.5 real fps in that room's light).
- Not testable there: the GTK window (SSH/tty, no display) and the virtual camera (loopback module
  not installed). Both environmental, not code.
- Kernel 6.8 is stricter about UVC control sizes (EOVERFLOW on a >4-byte read of a 4-byte control);
  the app only ever reads <=4 from spaces 1/2/3, so it is unaffected. An inline ffmpeg test command
  without -nostdin ate piped-script bytes; the app's own ffmpeg calls all pass -nostdin.
- TODO (cosmetic, re-check when a local HP camera is attached): confirm the R/G order in the
  `hpcam status` gain readout; the read and write paths are symmetric by construction, so this is a
  display check only.
