#!/usr/bin/env bash
# Installs Clip Ça on Linux Mint (XFCE, X11) and other Ubuntu/Debian-based systems, for the current user.
# Usage, from the repo folder:  bash linux/install.sh
# Asks for your password once (apt). Re-run it to update. Uninstall: bash linux/install.sh --uninstall
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$HOME/.local/share/clipca"
MENU="$HOME/.local/share/applications/clipca.desktop"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/clipca.desktop"
BIN="$HOME/.local/bin/clipca"

if [ "${1:-}" = "--uninstall" ]; then
    pkill -f "$APP_DIR/clipper_app.py" || true
    rm -rf "$APP_DIR" "$MENU" "$AUTOSTART" "$BIN"
    echo "Clip Ça removed. Your clips and OBS were left alone."
    exit 0
fi

command -v apt-get >/dev/null || { echo "This installer needs an Ubuntu/Debian-based system (Linux Mint is one)."; exit 1; }

echo "== System packages (Linux asks for your password)"
# python3-gi + ayatana appindicator: the tray icon; libportaudio2: the mic for "clip ça"; ffmpeg: compression;
# python3-evdev + python3-xlib: the hotkey (pynput needs them, and pip would have to compile evdev)
sudo apt-get update -qq
sudo apt-get install -y python3-venv python3-tk python3-gi gir1.2-ayatanaappindicator3-0.1 libportaudio2 ffmpeg \
    xdg-user-dirs x11-xserver-utils pciutils curl unzip sound-theme-freedesktop pulseaudio-utils python3-evdev python3-xlib
# OBS from its official PPA: Mint/Ubuntu's own obs-studio package is built without obs-websocket
if [ ! -e /usr/lib/x86_64-linux-gnu/obs-plugins/obs-websocket.so ]; then
    sudo apt-get install -y software-properties-common
    sudo add-apt-repository -y ppa:obsproject/obs-studio
    sudo apt-get update -qq
    sudo apt-get install -y obs-studio
fi

echo "== App files in $APP_DIR"
mkdir -p "$APP_DIR"
cp "$REPO/clipper_app.py" "$REPO/icon.png" "$APP_DIR/"
python3 -m venv --system-site-packages "$APP_DIR/venv"  # system site: reuses apt's tkinter and gi for the tray
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q obsws-python==1.8.1 vosk==0.3.45 sounddevice==0.5.6 pystray==0.19.5 \
    'pillow>=10,<14' 'pynput>=1.7,<2'

echo "== Offline voice models (about 80 MB, once)"
mkdir -p "$APP_DIR/models"
for m in vosk-model-small-fr-0.22 vosk-model-small-en-us-0.15; do
    if [ ! -d "$APP_DIR/models/$m" ]; then
        curl -fsSL "https://alphacephei.com/vosk/models/$m.zip" -o "/tmp/$m.zip"
        unzip -q -o "/tmp/$m.zip" -d "$APP_DIR/models"
        rm "/tmp/$m.zip"
    fi
done

echo "== Menu entry, 'clipca' command and login item"
RUN="\"$APP_DIR/venv/bin/python\" \"$APP_DIR/clipper_app.py\""
mkdir -p "$(dirname "$MENU")" "$(dirname "$AUTOSTART")" "$(dirname "$BIN")"
cat > "$MENU" <<EOF
[Desktop Entry]
Type=Application
Name=Clip Ça
Comment=Save the last seconds of your screen with a hotkey or your voice
Exec=$RUN
Icon=$APP_DIR/icon.png
Categories=AudioVideo;Recorder;
Terminal=false
EOF
# same file the app writes when you tick "Start when you log in"
printf '[Desktop Entry]\nType=Application\nName=Clip Ça\nIcon=%s\nExec=%s --background\nX-GNOME-Autostart-enabled=true\n' \
    "$APP_DIR/icon.png" "$RUN" > "$AUTOSTART"
printf '#!/bin/sh\nexec %s "$@"\n' "$RUN" > "$BIN"
chmod +x "$BIN"

echo "== Check"
"$APP_DIR/venv/bin/python" "$APP_DIR/clipper_app.py" --selftest
cat "${XDG_CONFIG_HOME:-$HOME/.config}/ClipCa/selftest.txt"; echo

if [ "${XDG_SESSION_TYPE:-x11}" = "wayland" ]; then
    echo "Note: you're on Wayland. The hotkey only works on X11 (Linux Mint XFCE is X11); voice and buttons work."
fi
echo "Done. Open Clip Ça from the menu (Sound & Video). It also starts when you log in; 'clipca' works after your next login."
