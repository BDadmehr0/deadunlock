#!/usr/bin/env bash
# Install prerequisites on supported Linux distributions and set up a local venv.
set -euo pipefail

usage() {
    cat <<'HELP'
Usage: scripts/setup-linux.sh [--skip-system]

Detect Arch, Debian/Ubuntu, Fedora, or openSUSE and install the system packages
with sudo, then create/reuse .venv and install Python requirements. Arch uses
pacman -Syu and therefore upgrades the entire system. Package managers may
ask for confirmation. Steam and Proton must be installed separately.

  --skip-system  Skip system packages (also works on other distributions).
  -h, --help     Show this help.
HELP
}

skip_system=false
case "${1:-}" in
    "") ;;
    --skip-system) skip_system=true ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac
if (( $# > 1 )); then usage >&2; exit 2; fi
if (( EUID == 0 )); then
    echo "Run as a normal user, not root; sudo is used only for system packages." >&2
    exit 1
fi

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$project_dir/requirements.txt" ]] || { echo "requirements.txt not found." >&2; exit 1; }

if ! $skip_system; then
    release_file="${DEADUNLOCK_OS_RELEASE:-/etc/os-release}"
    [[ -r "$release_file" ]] || {
        echo "Cannot read OS release information; install prerequisites manually and use --skip-system." >&2
        exit 1
    }
    distro_id=""; distro_like=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        case "$line" in
            ID=*) value="${line#ID=}"; key=id ;;
            ID_LIKE=*) value="${line#ID_LIKE=}"; key=like ;;
            *) continue ;;
        esac
        value="${value#\"}"; value="${value%\"}"
        value="${value#\'}"; value="${value%\'}"
        if [[ "$key" == id ]]; then distro_id="${value,,}"; else distro_like="${value,,}"; fi
    done < "$release_file"
    families=" $distro_id $distro_like "
    if [[ "$families" =~ (^|[[:space:]])(arch|manjaro)([[:space:]]|$) ]]; then
        manager=pacman
    elif [[ "$families" =~ (^|[[:space:]])(debian|ubuntu)([[:space:]]|$) ]]; then
        manager=apt-get
    elif [[ "$families" =~ (^|[[:space:]])(fedora|rhel)([[:space:]]|$) ]]; then
        manager=dnf
    elif [[ "$families" =~ (^|[[:space:]])(opensuse|opensuse-leap|opensuse-tumbleweed|suse)([[:space:]]|$) ]]; then
        manager=zypper
    else
        echo "Unsupported distribution ($distro_id). Install prerequisites manually and use --skip-system." >&2
        exit 1
    fi
    command -v "$manager" >/dev/null 2>&1 || {
        echo "Detected $distro_id but $manager is unavailable; use --skip-system after manual installation." >&2
        exit 1
    }
    command -v sudo >/dev/null 2>&1 || {
        echo "sudo not found; install prerequisites manually and use --skip-system." >&2
        exit 1
    }
    case "$manager" in
        pacman)
            echo "Arch: pacman -Syu upgrades the entire system and may ask for confirmation."
            sudo pacman -Syu --needed python tk libglvnd libx11 libxi libxtst libxcb \
                libxkbcommon-x11 xcb-util-cursor xcb-util-image xcb-util-keysyms \
                xcb-util-renderutil xcb-util-wm xorg-xev
            ;;
        apt-get)
            sudo apt-get update
            sudo apt-get install python3 python3-venv python3-tk libgl1 libx11-6 libxi6 \
                libxtst6 libx11-xcb1 libxcb1 libxkbcommon-x11-0 libxcb-cursor0 \
                libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
                libxcb-render-util0 libxcb-xinerama0 libxcb-xfixes0 x11-utils
            ;;
        dnf)
            sudo dnf install python3 python3-pip python3-tkinter libglvnd-glx libX11 libXi \
                libXtst libxcb libxkbcommon-x11 xcb-util-cursor xcb-util-image \
                xcb-util-keysyms xcb-util-renderutil xcb-util-wm xorg-x11-utils
            ;;
        zypper)
            sudo zypper install python3 python3-pip python3-tk libglvnd libX11-6 libXi6 \
                libXtst6 libxcb1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 \
                libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 xev
            ;;
    esac
fi

python_bin=""
for candidate in python3 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1 && \
       "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
        python_bin="$candidate"
        break
    fi
done
if [[ -z "$python_bin" ]]; then
    echo "Python 3.11 or newer is required; install it and retry with --skip-system." >&2
    exit 1
fi
if [[ ! -e "$project_dir/.venv" ]]; then
    "$python_bin" -m venv "$project_dir/.venv"
elif [[ ! -x "$project_dir/.venv/bin/python" ]]; then
    echo "Existing .venv is incomplete. Remove or repair it, then retry." >&2
    exit 1
fi
venv_python="$project_dir/.venv/bin/python"
if ! "$venv_python" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    echo "Existing .venv needs Python 3.11 or newer; recreate it and retry." >&2
    exit 1
fi
if ! "$venv_python" -c 'import tkinter'; then
    echo "Tkinter is unavailable for this Python; install your distribution's Python Tk package." >&2
    exit 1
fi
"$venv_python" -m pip install -r "$project_dir/requirements.txt"
printf '\nSetup complete. Start Deadlock through Proton, then run:\n'
printf '  cd %q\n  .venv/bin/python -m deadlock\n' "$project_dir"
printf 'Steam/Proton and process permissions must be configured separately.\n'
