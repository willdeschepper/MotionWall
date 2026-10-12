#!/usr/bin/env bash
set -euo pipefail
motionwall_source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [ "$(id -u)" -eq 0 ]; then
    echo "Execute ./install.sh como seu usuário normal. O instalador pede sudo somente para o pacote." >&2
    exit 1
fi
if ! command -v apt-get >/dev/null || ! command -v dpkg-deb >/dev/null; then
    echo "Este instalador requer Ubuntu/Debian com apt e dpkg." >&2
    exit 1
fi
/usr/bin/python3 "$motionwall_source_root/tools/build_deb.py"
motionwall_version="$(cd -- "$motionwall_source_root" && /usr/bin/python3 -m motionwall --version)"
motionwall_package="$motionwall_source_root/dist/motionwall_${motionwall_version}_all.deb"
sudo apt-get install -y -- "$motionwall_package"
# Run as the original desktop user: never install the extension into root's home.
/usr/bin/motionwall --install-extension
if command -v gnome-extensions >/dev/null 2>&1; then
    if ! gnome-extensions enable motionwall@willdeschepper.github.io; then
        echo "O GNOME descobrirá a integração depois que você sair e entrar na sessão."
    fi
fi
echo "MotionWall instalado. Abra pela lista de aplicativos ou execute: motionwall"
