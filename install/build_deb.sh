#!/bin/sh
# Build hp-webcam-tuner_<version>_all.deb into dist/ (no root needed).
#   sh install/build_deb.sh 0.1.0
set -eu
umask 022
VERSION=${1:?usage: build_deb.sh VERSION}
HERE=$(cd "$(dirname "$0")/.." && pwd)
PKG=hp-webcam-tuner
OUT="$HERE/dist"
ROOT=$(mktemp -d)
trap 'rm -rf "$ROOT"' EXIT
chmod 0755 "$ROOT"
APP=/usr/share/$PKG

# program files (the static design-gate harness is a development file and is left out)
mkdir -p "$ROOT$APP/ui" "$ROOT/usr/bin" "$ROOT/usr/share/applications" "$ROOT/usr/share/doc/$PKG" \
         "$ROOT/usr/lib/modules-load.d" "$ROOT/usr/lib/modprobe.d" "$ROOT/DEBIAN"
install -m 0644 "$HERE/hpcam.py" "$HERE/hpcam_web.py" "$HERE/hpcam_app.py" "$ROOT$APP/"
install -m 0644 "$HERE/ui/index.html" "$HERE/ui/app.css" "$HERE/ui/app.js" "$HERE/ui/tokens.css" \
                "$HERE/ui/CREDITS.md" "$ROOT$APP/ui/"
install -m 0644 "$HERE/README.md" "$HERE/NOTES.md" "$ROOT/usr/share/doc/$PKG/"

cat > "$ROOT/usr/bin/hp-webcam-tuner" <<EOF
#!/bin/sh
exec python3 $APP/hpcam_app.py "\$@"
EOF
cat > "$ROOT/usr/bin/hpcam" <<EOF
#!/bin/sh
exec python3 $APP/hpcam.py "\$@"
EOF
chmod 0755 "$ROOT/usr/bin/hp-webcam-tuner" "$ROOT/usr/bin/hpcam"

cat > "$ROOT/usr/share/applications/$PKG.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=HP Webcam
Comment=Tune the HP USB Webcam picture
Exec=hp-webcam-tuner
Icon=camera-web
Categories=AudioVideo;Video;
Keywords=webcam;camera;white balance;
EOF

# virtual camera: load v4l2loopback at boot as /dev/video10 (needs v4l2loopback-dkms, a Recommends)
printf 'v4l2loopback\n' > "$ROOT/usr/lib/modules-load.d/$PKG.conf"
printf 'options v4l2loopback video_nr=10 card_label="HP Webcam (tuned)" exclusive_caps=1\n' \
    > "$ROOT/usr/lib/modprobe.d/$PKG.conf"

cat > "$ROOT/usr/share/doc/$PKG/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: $PKG
Source: https://github.com/skinnie/hp-webcam-tuner

Files: *
License: MIT
 $(sed -n '3p' "$HERE/LICENSE")
 See /usr/share/common-licenses or https://opensource.org/licenses/MIT for the full text.

Files: ui/app.css
Comment: switch, slider, button and spinner adapted from Uiverse.io (Galaxy), MIT; see ui/CREDITS.md
License: MIT
EOF

cat > "$ROOT/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: video
Priority: optional
Architecture: all
Depends: python3, python3-numpy, ffmpeg, python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1, xdg-user-dirs
Recommends: v4l2loopback-dkms
Maintainer: andrepsfaria <5618623+skinnie@users.noreply.github.com>
Homepage: https://github.com/skinnie/hp-webcam-tuner
Installed-Size: $(du -sk "$ROOT/usr" | cut -f1)
Description: picture tuning for the HP USB Webcam (03f0:8007)
 Desktop app and command line tool for the HP USB Webcam (AU165AA), a Vimicro
 UVC camera with no white balance of its own. Uses the camera's undocumented
 vendor extension unit to set its colour gains, with automatic white balance,
 all picture controls, photos, and a virtual camera for video-call apps.
EOF

# load the virtual camera right away when the module is available (it loads at boot anyway)
cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = configure ] && modinfo v4l2loopback >/dev/null 2>&1; then
    modprobe v4l2loopback 2>/dev/null || true
fi
exit 0
EOF
chmod 0755 "$ROOT/DEBIAN/postinst"

mkdir -p "$OUT"
dpkg-deb --root-owner-group -Zxz --build "$ROOT" "$OUT/${PKG}_${VERSION}_all.deb"
echo "built $OUT/${PKG}_${VERSION}_all.deb"
