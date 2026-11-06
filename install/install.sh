#!/bin/sh
# User-level install for the HP USB Webcam tuner (no root needed).
#   sh install/install.sh            add "HP Webcam" to the applications menu
#   sh install/install.sh --service  also keep settings applied after replugging (systemd user service)
#   sh install/install.sh --uninstall
# Root-only extras (virtual camera, uncompressed video): sudo sh install/setup-root.sh
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/hpcam.service"

if [ "${1:-}" = "--uninstall" ]; then
    systemctl --user disable --now hpcam.service 2>/dev/null || true
    rm -f "$APPS/hpcam.desktop" "$UNIT"
    echo "Removed the launcher and the service. Your profile stays in ~/.config/hpcam/."
    exit 0
fi

for dep in python3 ffmpeg; do
    command -v "$dep" >/dev/null || { echo "Missing $dep" >&2; exit 1; }
done
python3 -c 'import numpy' 2>/dev/null || { echo "Missing python3-numpy" >&2; exit 1; }
python3 -c 'import gi; gi.require_version("WebKit2", "4.1")' 2>/dev/null \
    || echo "Note: WebKitGTK 4.1 bindings (gir1.2-webkit2-4.1) not found; use: python3 $HERE/hpcam_app.py --browser"

mkdir -p "$APPS"
cat > "$APPS/hpcam.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=HP Webcam
Comment=Tune the HP USB Webcam picture
Exec=python3 $HERE/hpcam_app.py
Icon=camera-web
Categories=AudioVideo;Video;
DESK
echo "Added HP Webcam to the applications menu."

if [ "${1:-}" = "--service" ]; then
    mkdir -p "$(dirname "$UNIT")"
    cat > "$UNIT" <<UNITF
[Unit]
Description=HP USB Webcam: keep tuned settings applied

[Service]
ExecStart=python3 $HERE/hpcam.py run
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
UNITF
    systemctl --user daemon-reload
    systemctl --user enable --now hpcam.service
    echo "Background service enabled."
fi
