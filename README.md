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

Replace `12345` with the real PID. The process must have file-backed
`client.dll` and `schemasystem.dll` mappings visible in `/proc/<pid>/maps`.
The scanner reads readable file-backed mappings and fails if required
signatures are missing; it cannot find code in anonymous-only mappings. PE
mapping layouts and game updates may require different signatures or module
base calculations. Hardcoded entity and camera offsets can also become stale.
Inspect and update `signature_patterns.py` and `deadlock/mem_offsets.py` for
the specific game version before relying on any results. A match alone does
not establish that an offset is correct; an incorrect write can corrupt the
game process.

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
`deadlock/esp.py` implements the Qt overlay. `deadlock/memory.py` contains the
game-specific memory logic; `deadlock/aimbot.py` and `aimbot_gui.py` implement
the aimbot and its Tk interface.
