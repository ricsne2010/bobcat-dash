#!/bin/bash
# Bobcat dash: one-command setup of a fresh Raspberry Pi OS Lite card.
#
#   1. Flash Raspberry Pi OS Lite (64-bit) with Raspberry Pi Imager. In its settings, set the hostname
#      (e.g. bobcat-dash), a username and password, your Wi-Fi, and turn on SSH.
#   2. Boot the Pi (it needs internet for this), log in or ssh in, then:
#        sudo apt install -y git
#        git clone https://github.com/ricsne2010/bobcat-dash.git
#        sudo bash bobcat-dash/tools/setup-pi.sh
#   3. Reboot when it says so. The dash starts on its own from then on.
#
# Safe to run again (after a software update, or if something failed): it only adds what's missing.
# Options:
#   --resolution WxH   monitor resolution (default 1024x768)
#   --fast-boot        also turn off Bluetooth and the wait-for-network step (faster key-on to gauges)
#   --no-power-hold    for a hand-wired setup without the breakout board's power-hold circuit
set -euo pipefail

RES=1024x768
FAST=0
HOLD=1
while [ $# -gt 0 ]; do
    case "$1" in
        --resolution) RES="$2"; shift 2 ;;
        --fast-boot) FAST=1; shift ;;
        --no-power-hold) HOLD=0; shift ;;
        *) echo "unknown option: $1"; exit 2 ;;
    esac
done

[ "$(id -u)" = 0 ] || { echo "Run it with sudo:  sudo bash $0"; exit 1; }
USER_NAME="${SUDO_USER:-pi}"
[ "$USER_NAME" != root ] || { echo "Run it as your normal user with sudo, not as root."; exit 1; }
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
BOOT=/boot/firmware
[ -f "$BOOT/config.txt" ] || BOOT=/boot
CONFIG="$BOOT/config.txt"
CMDLINE="$BOOT/cmdline.txt"
[ -f "$REPO/dash.py" ] || { echo "Can't find dash.py next to tools/ ($REPO)"; exit 1; }
[ -f "$CONFIG" ] && [ -f "$CMDLINE" ] || { echo "No $CONFIG / $CMDLINE: is this Raspberry Pi OS?"; exit 1; }
echo "== M.O.S.S. (Bobcat dash) setup: user $USER_NAME, software in $REPO, screen $RES"

step() { echo; echo "== $*"; }

# config.txt: add each line once, in an [all] section of our own at the end
config_line() {
    grep -qxF "$1" "$CONFIG" && return 0
    grep -qxF "# --- bobcat-dash ---" "$CONFIG" || printf '\n# --- bobcat-dash ---\n[all]\n' >> "$CONFIG"
    echo "$1" >> "$CONFIG"
    echo "   config.txt: + $1"
}
# cmdline.txt is ONE line: add each word once (replace an older video= for HDMI-A-1)
cmdline_word() {
    local line; line="$(head -n 1 "$CMDLINE")"
    case "$1" in
        video=HDMI-A-1:*) line="$(printf '%s\n' "$line" | tr ' ' '\n' | grep -v '^video=HDMI-A-1:' | tr '\n' ' ')" ;;
    esac
    case " $line " in *" $1 "*) ;; *) line="$line $1" ;; esac
    printf '%s\n' "$(echo "$line" | tr -s ' ' | sed 's/^ //; s/ $//')" > "$CMDLINE"
}

step "Packages"
apt-get update
apt-get install -y python3-pygame python3-gpiozero python3-lgpio python3-smbus2 python3-pil \
    python3-qrcode i2c-tools git rpd-plym-splash

apt-get install -y util-linux-extra 2>/dev/null || true    # hwclock: the web page saves the time in the Pi 5 RTC

step "I2C (the ADC and the tilt sensor)"
raspi-config nonint do_i2c 0

step "Boot configuration ($CONFIG)"
config_line "dtoverlay=w1-gpio"            # temperatures: DS18B20s on GPIO 4
config_line "dtoverlay=max98357a"          # speaker: MAX98357A amp (mono or stereo board)
config_line "disable_splash=1"             # no rainbow square at boot
config_line "dtparam=rtc_bbat_vchg=3000000"  # Pi 5 clock battery (ML-2020): keep it charged (ignored on a Pi 4)
if [ "$HOLD" = 1 ]; then
    config_line "gpio=26=op,dh"            # HOLD: keep the board's power on from the moment the Pi starts
fi
cmdline_word "video=HDMI-A-1:${RES}@60D"   # HDMI on even if the monitor powers up late
cmdline_word "quiet"
cmdline_word "splash"
cmdline_word "logo.nologo"
cmdline_word "vt.global_cursor_default=0"
echo "   cmdline.txt: $(cat "$CMDLINE")"

step "Dash service"
sed -e "s#^User=pi#User=$USER_NAME#" -e "s#/home/pi/bobcat-dash#$REPO#g" \
    "$REPO/bobcat-dash.service" > /etc/systemd/system/bobcat-dash.service
systemctl daemon-reload
systemctl enable bobcat-dash

step "Service Wi-Fi and USB stick helpers"
install -m 755 "$REPO/tools/bobcat-dash-wifi" "$REPO/tools/bobcat-dash-usb" "$REPO/tools/bobcat-dash-reset-code" \
    "$REPO/tools/bobcat-dash-clock" /usr/local/bin/
sed "s/^pi ALL/$USER_NAME ALL/" "$REPO/tools/bobcat-dash-sudoers" > /tmp/bobcat-dash-sudoers
if visudo -cf /tmp/bobcat-dash-sudoers >/dev/null; then
    install -m 440 /tmp/bobcat-dash-sudoers /etc/sudoers.d/bobcat-dash
else
    echo "   !! sudoers file didn't check out; skipped (no key-off power off, service Wi-Fi or USB stick)"
fi
rm -f /tmp/bobcat-dash-sudoers
if ! nmcli -t -f WIFI general 2>/dev/null | grep -q enabled; then
    echo "   !! Wi-Fi is off or blocked: set the Wi-Fi country (sudo raspi-config > Localisation > WLAN Country)"
fi

if [ "$HOLD" = 1 ]; then
    step "Key-off shutdown (power hold)"
    install -m 755 "$REPO/tools/bobcat-dash-poweroff" /usr/lib/systemd/system-shutdown/
    install -m 755 "$REPO/tools/bobcat-dash-keywatch" /usr/local/bin/
    install -m 644 "$REPO/tools/bobcat-dash-keywatch.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable bobcat-dash-keywatch
fi

step "Boot splash"
W="${RES%x*}"; H="${RES#*x}"
if [ "$RES" != 1024x768 ]; then
    for f in "$REPO/splash/splash-${RES}.png"; do
        [ -f "$f" ] && cp "$f" "$REPO/splash/splash.png" && echo "   using splash-${RES}.png"
    done
fi
sudo -u "$USER_NAME" env SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
    python3 "$REPO/dash.py" --boot-splash || echo "   !! couldn't make the boot splash; the Pi's own one stays"
THEME=/usr/share/plymouth/themes/pix
if [ -f "$REPO/splash/boot-splash.png" ] && [ -d "$THEME" ]; then
    [ -f "$USER_HOME/splash-original.png" ] || cp "$THEME/splash.png" "$USER_HOME/splash-original.png"
    cp "$REPO/splash/boot-splash.png" "$THEME/splash.png"
    plymouth-set-default-theme --rebuild-initrd pix
fi

step "Data folder and permissions"
sudo -u "$USER_NAME" mkdir -p "$USER_HOME/bobcat-dash-data"
chown -R "$USER_NAME:$USER_NAME" "$REPO"

if [ "$FAST" = 1 ]; then
    step "Faster boot"
    systemctl disable bluetooth hciuart 2>/dev/null || true
    systemctl disable NetworkManager-wait-online 2>/dev/null || true
fi

step "Done"
cat <<EOF
Reboot now:   sudo reboot
After the reboot the splash shows, then the dash starts by itself.

Then:
  - Check the ADC answers:          i2cdetect -y 1        (should show 48)
  - Calibrate (README, Calibrating): sudo systemctl stop bobcat-dash; python3 $REPO/dash.py --calibrate
  - Name the temperature sensors:   python3 $REPO/dash.py --temps
  - Pi 5 only, optional:            sudo rpi-eeprom-config --edit   and add   PSU_MAX_CURRENT=5000
  - When it all works, save a copy of the card (README, "Backing up the SD card").
EOF
