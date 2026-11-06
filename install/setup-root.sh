#!/bin/sh
# One-time root setup for the HP USB Webcam tuner.
#   sudo ./setup-root.sh          install and load now
#   sudo ./setup-root.sh --undo   remove both files and unload the virtual camera
#
# What it does: loads v4l2loopback at boot as /dev/video10 named "HP Webcam (tuned)", so the app
# can send its processed picture to video-call apps.
#
# Not done on purpose: uvcvideo quirks=0x80 (FIX_BANDWIDTH). Tested on this camera: it removes the
# "No space left on device" error for uncompressed YUYV, but 640x480 then delivers no frames at any
# rate (only 352x288 and smaller work), so it gains nothing over 640x480 MJPEG. Earlier versions of
# this script set it; running this version removes it.
set -eu
LOAD=/etc/modules-load.d/hpcam.conf
OPTS=/etc/modprobe.d/hpcam.conf

if [ "$(id -u)" != 0 ]; then echo "Run with sudo." >&2; exit 1; fi

if [ "${1:-}" = "--undo" ]; then
    rm -f "$LOAD" "$OPTS"
    modprobe -r v4l2loopback 2>/dev/null || echo "v4l2loopback in use or not loaded; it goes away after reboot."
    echo "Removed."
    exit 0
fi

printf 'v4l2loopback\n' > "$LOAD"
cat > "$OPTS" <<'CONF'
# HP USB Webcam tuner (hpwebcam/install/setup-root.sh)
options v4l2loopback video_nr=10 card_label="HP Webcam (tuned)" exclusive_caps=1
CONF
echo "Wrote $LOAD and $OPTS"

modprobe v4l2loopback && echo "Virtual camera loaded: /dev/video10"
if [ "$(cat /sys/module/uvcvideo/parameters/quirks 2>/dev/null)" = 128 ]; then
    # left over from an earlier version of this script
    if modprobe -r uvcvideo 2>/dev/null && modprobe uvcvideo; then
        echo "Camera driver reloaded without the old bandwidth quirk"
    else
        echo "Old bandwidth quirk still active until reboot (a camera app is open)."
    fi
fi
