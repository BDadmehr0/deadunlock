#!/usr/bin/env bash
# Install the Arch Linux system prerequisites and the project's Python dependencies.
set -euo pipefail

usage() {
    cat <<'HELP'
Usage: scripts/setup-arch.sh [--skip-system]

Set up DeadUnlock in a local .venv. By default this runs
  sudo pacman -Syu --needed <packages>
which updates the entire system and asks for confirmation. Steam and Proton
must be installed and configured separately. The script does not modify ptrace
settings or start the application.

  --skip-system  Skip pacman; use system prerequisites already installed.
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
if (( $# > 1 )); then
    usage >&2
    exit 2
fi

if (( EUID == 0 )); then
    echo "Run this script as your normal user, not root; it will use sudo for pacman." >&2
    exit 1
fi

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -f "$project_dir/requirements.txt" ]]; then
    echo "Cannot find requirements.txt in $project_dir" >&2
    exit 1
fi

if ! $skip_system; then
    if ! command -v pacman >/dev/null 2>&1; then
        echo "pacman not found. This script targets Arch Linux; see README.md for other systems." >&2
        exit 1
    fi
    if ! command -v sudo >/dev/null 2>&1; then
        echo "sudo not found. Install the system prerequisites manually, then use --skip-system." >&2
        exit 1
    fi
    echo "Installing prerequisites and updating the system with pacman."
    sudo pacman -Syu --needed \
        python tk libglvnd libx11 libxi libxtst libxcb libxkbcommon-x11 \
        xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil \
        xcb-util-wm xorg-xev
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3.11 or newer is required." >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    echo "Python 3.11 or newer is required." >&2
    exit 1
fi

if [[ ! -e "$project_dir/.venv" ]]; then
    python3 -m venv "$project_dir/.venv"
elif [[ ! -x "$project_dir/.venv/bin/python" ]]; then
    echo "Existing .venv is incomplete. Remove or repair it, then retry." >&2
    exit 1
fi

"$project_dir/.venv/bin/python" -m pip install -r "$project_dir/requirements.txt"
printf '\nSetup complete. Start Deadlock through Proton in an X11 session, then run:\n'
printf '  cd %q\n  .venv/bin/python -m deadlock\n' "$project_dir"
printf '\nSee docs/arch-linux-fa.md for permissions, ESP, and troubleshooting.\n'
