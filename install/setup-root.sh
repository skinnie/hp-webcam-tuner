#!/bin/sh
# One-time root setup for the HP USB Webcam tuner.
#   sudo ./setup-root.sh          install and load now
#   sudo ./setup-root.sh --undo   remove both files and unload the virtual camera
#
# What it does:
#  1. Virtual camera: loads v4l2loopback at boot as /dev/video10 named "HP Webcam (tuned)", so the
#     app can send its processed picture to video-call apps.
#  2. Uncompressed video: uvcvideo quirk 0x80 (FIX_BANDWIDTH). The camera asks for more USB
#     bandwidth than it needs, so YUYV (uncompressed) capture fails with "No space left on device".
#     The quirk makes the driver compute the real need. It applies to all UVC cameras, and only
#     changes how bandwidth is requested for uncompressed formats.
set -eu
LOAD=/etc/modules-load.d/hpcam.conf
OPTS=/etc/modprobe.d/hpcam.conf

if [ "$(id -u)" != 0 ]; then echo "Run with sudo." >&2; exit 1; fi

if [ "${1:-}" = "--undo" ]; then
    rm -f "$LOAD" "$OPTS"
    modprobe -r v4l2loopback 2>/dev/null || echo "v4l2loopback in use or not loaded; it goes away after reboot."
    echo "Removed. The uvcvideo quirk stays active until the camera driver reloads or the machine reboots."
    exit 0
fi

printf 'v4l2loopback\n' > "$LOAD"
cat > "$OPTS" <<'CONF'
# HP USB Webcam tuner (hpwebcam/install/setup-root.sh)
options v4l2loopback video_nr=10 card_label="HP Webcam (tuned)" exclusive_caps=1
options uvcvideo quirks=0x80
CONF
echo "Wrote $LOAD and $OPTS"

modprobe v4l2loopback && echo "Virtual camera loaded: /dev/video10"
if modprobe -r uvcvideo 2>/dev/null; then
    modprobe uvcvideo && echo "Camera driver reloaded with quirks=0x80"
else
    echo "Camera driver is in use (close apps using a camera); the quirk applies after reboot or replug+reload."
fi
