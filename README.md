# DeadUnlock (Linux / Proton)

DeadUnlock is an external aimbot and ESP experiment for Valve's Deadlock. It
reads and writes the game's memory from a separate process. This Linux port
**targets the Windows game running under Proton**, not a native Linux build.
It is experimental: the original Windows signatures and structure offsets may
not match the current game or Proton's memory mappings. Neither live game
compatibility nor the overlay has been verified by this port.

This project is for educational and research purposes. Using it may violate
Deadlock's rules and can result in account penalties. Do not use it where you
lack permission to inspect or modify a process.

## Requirements

- Linux, Python 3.11, Steam with Deadlock running under Proton.
- An **X11 session** with the XTEST extension for global input and synthetic
  events. Native Wayland is not supported; Xwayland does not provide global
  input for native Wayland windows. A game using exclusive input grabs or raw
  input may not accept synthesized events.
- For ESP, an X11 compositor, Qt's xcb platform dependencies, and a game window
  on the primary monitor at the monitor's full resolution. The overlay is a
  transparent, click-through, always-on-top window; window managers may differ
  in how they handle it. It does not track window position or multiple monitors.
  Use borderless/windowed mode; exclusive fullscreen may hide it.
- Permission to inspect and write the target process via `/proc/<pid>/mem`.
  Processes must normally run as the same user, be dumpable, and pass Linux
  ptrace/LSM checks. The port does not bypass game security mechanisms.

### Arch Linux

For Arch Linux, run `./scripts/setup-arch.sh` as a normal user. It uses
`sudo pacman -Syu --needed` (a full system upgrade with confirmation), creates
or reuses `.venv`, and installs the Python requirements. Steam and Proton must
be installed separately. The script does not change ptrace settings. Use
`--skip-system` to skip pacman. See the [Persian Arch guide](docs/arch-linux-fa.md)
for manual installation, execution, permissions, and troubleshooting.

### Debian / Ubuntu

On Debian/Ubuntu, install Python's venv and Tk support and Qt/X11 runtime
libraries (other distributions use different package names):

```bash
sudo apt install python3-venv python3-tk libgl1 libxcb-xinerama0 libxkbcommon-x11-0
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Additional Qt xcb libraries may be needed depending on the distribution. If
Qt cannot load its `xcb` plugin, consult the distribution's Qt/X11 packages.

### Process permissions

On many systems Yama's `ptrace_scope=1` prevents access to an unrelated
process, even under the same account. Check it with:

```bash
cat /proc/sys/kernel/yama/ptrace_scope
```

If your security policy permits, an administrator can temporarily set it to
`0` with `sudo sysctl -w kernel.yama.ptrace_scope=0` and restore the previous
value afterward. This relaxes protections **system-wide**, not just for this
application. Other restrictions (such as SELinux, containers, or a non-dumpable
process) can still block access. Avoid running the GUI or game as root.

## Running

Start Deadlock in Proton first, then activate the virtual environment and run:

```bash
python -m deadlock.aimbot_gui  # settings and start/stop controls
python -m deadlock.aimbot      # command-line aimbot
python -m deadlock.esp         # transparent overlay
```

The ESP selects Qt's `xcb` backend by default when `DISPLAY` is set. If Qt is
explicitly configured for another backend, use the following from an X11 session:

```bash
QT_QPA_PLATFORM=xcb python -m deadlock.esp
```

On Wayland this uses Xwayland only and is experimental: compositor stacking,
transparency and global input may not work; an X11 login is recommended. A
compositor and the Qt xcb runtime libraries are still required.

If aim toggles but finds no target, the aimbot reports counts of unreadable,
same-team and non-positive-health slots while aiming. For a one-shot report
that opens the process memory **read-only** and does not inject input or write
angles, run while in a match:

```bash
python -m deadlock.diagnostics --pid 12345
```

Replace `12345` with the game PID, or omit `--pid` to use the normal process
discovery or `DEADUNLOCK_PID`. By default it checks the 15 slots the aimbot
scans and reports their read errors and team/health filters. To investigate
whether players exist outside that range, use `--slots 256` (up to 2048). Such
candidates are labelled as outside the aimbot's default scan; this diagnostic
does not expand the aimbot's target range. Use `--show-unreadable` to print
every failed slot. The process still requires read permission under
ptrace/Yama. A reported candidate does not validate the camera, bone indices,
game offsets, or writes.

The command-line aimbot and ESP accept `--debug`. The aimbot uses the left
mouse button to aim; the right button synthesizes a left click without aiming.
Map alternate fire in the game so the right button does not conflict. The GUI
allows changing the hero ability hotkeys. X11 key mappings are used for these
single-character keys. Synthetic inputs and game input handling depend on the
X server and Proton setup.

The default process name is `deadlock.exe`. If Proton exposes a different
name, set `DEADUNLOCK_PROCESS` to the exact executable name. Alternatively,
set `DEADUNLOCK_PID` to the actual game PID to avoid process-name ambiguity:

```bash
DEADUNLOCK_PID=12345 python -m deadlock.aimbot_gui
```

Replace `12345` with the real game PID, not Steam's `reaper` or another launcher.
For example, inspect `ps -u "$USER" -o pid,comm,args` and, when permitted, check
`/proc/<pid>/maps` for `client.dll`. The process must have a file-backed
`client.dll` header mapping visible there. The scanner validates the in-memory
PE header and scans readable file-backed and anonymous mappings within the
module's declared image size. `schemasystem.dll` is not required by the current
runtime and its legacy signature is not scanned. This is an
experimental approximation of Proton's layout, and fails if signatures are
missing. PE mapping layouts and game updates may require different signatures
or module base calculations. Hardcoded entity and camera offsets can also become stale.
Inspect and update `signature_patterns.py` and `deadlock/mem_offsets.py` for
the specific game version before relying on any results. A match alone does
not establish that an offset is correct; an incorrect write can corrupt the
game process.

If the local player reports an unknown hero ID (including `0`) or a null
pointer, the aimbot stops aiming and waits without repeatedly logging a
traceback. Enter a match with a selected hero and retry. If the warning
persists, the game version, process selection, signatures, or hardcoded offsets
may be incompatible. Do not treat a known hero ID or a signature match as
proof that memory addresses are safe to write.

The GUI may offer to open the project's release page when an update is
available. The command-line aimbot checks for updates at startup and exits if
one is available.

## Packaging

On Linux, build the GUI for the same architecture/distribution family with:

```bash
pip install pyinstaller
pyinstaller deadunlock.spec
./dist/deadunlock
```

This produces a Linux executable, not a Windows `.exe`. It still needs an X11
desktop, access to the game process, and compatible system libraries.

## Development

```bash
python -m unittest discover -s tests -v
python -m py_compile $(git ls-files '*.py')
```

`deadlock/linux_process.py` implements process access, `offset_finder.py`
scans loaded modules, `deadlock/linux_input.py` implements X11 input, and
`deadlock/esp.py` implements the Qt overlay, and `deadlock/diagnostics.py`
provides read-only player diagnostics. `deadlock/memory.py` contains the
game-specific memory logic; `deadlock/aimbot.py` and `aimbot_gui.py` implement
the aimbot and its Tk interface.
