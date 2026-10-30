# DeadUnlock (Linux / Proton)

Experimental aimbot and ESP for the Windows version of Deadlock running under
Proton. Game offsets, head targeting and the overlay may be outdated or wrong;
writing to incorrect addresses can corrupt the game process. There is no wall
visibility check. Use may violate game rules or lead to account penalties.

## Requirements

- Linux, Steam and Deadlock running under Proton; Python 3.11 or newer.
- An **X11 session** with XInput2 and XTEST. Xwayland is experimental: global
  input, stacking and transparency depend on the compositor. Native Wayland is
  not supported. Use borderless/windowed mode and a compositor for the ESP.
- Permission to access `/proc/<game-pid>/mem` under the same user. Do not run the
  game or GUI as root. The app does not bypass ptrace or other security controls.

## Install

Clone the repository, enter its directory and run as a normal user:

```bash
git clone https://github.com/BDadmehr0/deadunlock.git
cd deadunlock
./scripts/setup-linux.sh
```

The script detects Arch, Debian/Ubuntu, Fedora or openSUSE families, asks `sudo`
to install system packages, and creates or reuses `.venv`. On Arch it runs
`pacman -Syu`, **upgrading the entire system**. Package availability varies by
release and derivative; Steam and Proton are installed separately. The script
never changes ptrace settings. `./scripts/setup-linux.sh --help` lists options.

For another Linux distribution, or if packages are already installed, install
Python 3.11+, its venv/pip and Tk support, and Qt xcb, X11, XInput2, XTEST and
OpenGL runtime libraries using your distribution's packages. Then run:

```bash
./scripts/setup-linux.sh --skip-system
```

If the existing `.venv` uses an older Python or is incomplete, repair or
recreate it before retrying. On immutable systems install prerequisites in a
compatible environment with access to the host X11 display and game process.
The legacy Arch-only installer remains available as `scripts/setup-arch.sh`.

## Run

Start Deadlock in Proton, then:

```bash
.venv/bin/python -m deadlock
```

Press **Start** to run the aimbot and optional **ESP overlay**. Stop or close
the panel to stop both. In **Settings → Aim button**, choose **Mouse 4** or
**Mouse 5** (normally X11 button 8 or 9); hold it to aim and use left-click to
fire. The old default is Mouse 4. Configured hero ability locks can also keep
aim active without holding the button; right-click synthesizes left-click and
suppresses aim. Button mappings vary: use `xev` to inspect yours.

In **Settings → Target selection**, `distance` chooses the nearest living enemy
in 3D world space and checks again every 0.1 seconds while aiming. Only slots
1–15 are considered, including enemies behind walls or off-screen; there is no
visibility check. `fov` selects by angular distance from the crosshair. Distance
is the default for new settings, but an existing saved choice is preserved;
select `distance` and Stop/Start if your saved setting is `fov`.

**Aim Zones** sets head/body/legs weights and a global head adjustment. The
experimental skeleton reader tries to resolve bone names from the target's model
automatically. Its offsets are from a third-party build and are **not verified**
on the current Proton game; a plausible position is not a verified hitbox. The
game may not have refreshed a pose. Watch Logs for the selected bone or errors.
By default, if the requested bone is unavailable or implausible, aiming is
paused for that target instead of using a guessed height. The nearest target is
still selected by the configured selection mode, even if its skeleton is missing.

To permit the old estimated fallback, enable **Aim Zones → Allow estimated aim
when skeleton is unavailable**. **Hero Heights** sets those per-target estimates
above the scene origin (0–200 game units); defaults of 100/70/30 are uncalibrated.
The global head adjustment applies to both named bones and fallbacks; set it to
zero when testing the raw bone. Enable **Live Save** to
save valid panel changes to `deadlock/aimbot_settings.json` (next to the
executable for packaged builds). Without Live Save, valid settings are still
saved on Start or close. Saved edits do not change a running bot: **Stop** and
**Start** to apply them. Invalid edits leave the last valid JSON intact.

Standalone commands: `.venv/bin/python -m deadlock.aimbot_gui`,
`.venv/bin/python -m deadlock.aimbot`, or `.venv/bin/python -m deadlock.esp`.

## Troubleshooting

- If ESP fails with a Qt platform error, install your distribution's xcb runtime
  libraries, use an X11 session, and try `QT_QPA_PLATFORM=xcb .venv/bin/python -m deadlock`.
  Check the panel's **Logs** tab for overlay errors.
- If the game isn't found, identify the real game process (not Steam's `reaper`):
  `ps -u "$USER" -o pid,comm,args | grep -iE 'deadlock|project8'`. To override
  discovery, run `DEADUNLOCK_PID=12345 .venv/bin/python -m deadlock`, replacing
  `12345` with the game PID; it changes after a restart.
- For a **read-only** player report, run `.venv/bin/python -m deadlock.diagnostics
  --pid 12345 --slots 256`. Slots beyond 15 are diagnostic only; a candidate
  does not validate camera, bone, visibility or write offsets.
- To probe the candidate skeleton offsets without writes or input, run
  `.venv/bin/python -m deadlock.skeleton_diagnostics --pid 12345 --slot 0 --dump-names`
  (replace the PID; slot 0 is local). Use an enemy slot from the player report
  to inspect a target. Compare the printed positions while standing and moving;
  a successful probe is not proof of accurate hitboxes or fresh animation data.
- If process access is denied, inspect ptrace/LSM restrictions and
  `cat /proc/sys/kernel/yama/ptrace_scope`. If your security policy permits an
  administrator to temporarily set it to 0, restore its previous value after
  testing. This weakens protection **system-wide**; the installer never does it.

More Arch-specific details: [Persian guide](docs/arch-linux-fa.md).
