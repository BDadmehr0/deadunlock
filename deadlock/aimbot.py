from __future__ import annotations

"""Aimbot implementation used by :mod:`deadlock`.

The logic here aims to be straightforward and easy to maintain.  The
``Aimbot`` class exposes a ``run`` loop that continuously reads game
memory via :class:`deadlock.memory.DeadlockMemory` and adjusts the
player camera toward enemy targets.

Global input is provided by X11.
"""

from dataclasses import dataclass
import random
import time
import logging
import math
import argparse

from .linux_input import X11Input
from .heroes import get_body_bone_index, get_head_bone_index
from .helpers import calculate_camera_rotation, calculate_new_camera_angles
from .memory import DeadlockMemory, EntityUnavailable
from . import mem_offsets as mo
from .update_checker import ensure_up_to_date

logger = logging.getLogger(__name__)


@dataclass
class AimbotSettings:
    """Configuration for :class:`Aimbot`."""

    # Retained for loading old settings files; zone weights replace both options.
    headshot_probability: float = 0.25

    random_zones: bool = False
    head_enabled: bool = True
    body_enabled: bool = False
    legs_enabled: bool = False
    head_weight: int = 100
    body_weight: int = 25
    legs_weight: int = 25

    target_select_type: str = "fov"  # "distance" or "fov"
    #: prioritisation strategy when selecting targets

    smooth_speed: float = 5.0
    #: maximum angle change (degrees) per frame when locking on

    grey_talon_lock: float = 0.5
    #: seconds to keep aiming after Grey Talon's ability 1 (``Q``)

    grey_talon_lock_enabled: bool = True
    #: if ``True`` check for Grey Talon's ability 1 key

    grey_talon_key: int = ord("Q")
    #: virtual-key code for Grey Talon's lock trigger

    yamato_lock: float = 1.5
    #: seconds to keep aiming after Yamato's ability 1 (``Q``)

    yamato_lock_enabled: bool = True
    #: if ``True`` check for Yamato's ability 1 key

    yamato_key: int = ord("Q")
    #: virtual-key code for Yamato's lock trigger

    vindicta_lock: float = 0.65
    #: seconds to keep aiming after Vindicta's ability 4 (``R``)

    vindicta_lock_enabled: bool = True
    #: if ``True`` check for Vindicta's ability 4 key

    vindicta_key: int = ord("R")
    #: virtual-key code for Vindicta's lock trigger

    paradox_shortcut_enabled: bool = True
    #: if ``True`` trigger Paradox ability combo

    paradox_r_key: int = ord("R")
    #: key that initiates Paradox combo

    paradox_e_key: int = ord("E")
    #: key automatically pressed after ``paradox_r_key``

    headshot_on_acquire: bool = True
    #: Legacy setting retained for loading old configuration files; no longer used.

    def zone_weights(self) -> dict[str, int]:
        """Return manual weights for enabled zones, rejecting invalid settings."""
        weights = {}
        for zone in ("head", "body", "legs"):
            value = getattr(self, f"{zone}_weight")
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                raise ValueError(f"{zone.title()} weight must be an integer from 0 to 100")
            if getattr(self, f"{zone}_enabled") and value:
                weights[zone] = value
        if not weights:
            raise ValueError("Select at least one zone with a positive weight")
        return weights


class Aimbot:
    """Basic aimbot controller."""
    
    def __init__(self, mem: DeadlockMemory, settings: AimbotSettings | None = None) -> None:
        """Create a new aimbot bound to ``mem``."""

        self.mem = mem
        self.settings = settings or AimbotSettings()
        self._zone_weights = (
            {zone: random.randint(1, 100) for zone in ("head", "body", "legs")}
            if self.settings.random_zones else self.settings.zone_weights()
        )
        self.input = X11Input()
        self.locked_on: int | None = None
        self.force_aim_until: float = 0.0
        self.paused = False
        self.stop_requested = False

        # Cache the zone briefly to avoid switching on every frame.
        self._zone_cache: str | None = None
        self._zone_cache_time = float("-inf")
        self._zone_cache_interval = 0.4
        logger.info("Aim zone weights for this run: %s", self._zone_weights)

        self._last_lock_lost: float = 0.0
        self._last_bad_bone_warning: float = float("-inf")

        # Paradox shortcut state
        self._paradox_next_e: float = 0.0
        self._paradox_r_held: bool = False

        logger.info("Aimbot initialised with settings: %s", self.settings)

    def _update_ability_lock(self, hero) -> None:
        """Extend ``force_aim_until`` when ability keys are pressed."""
        now = time.time()
        if hero.name == "GreyTalon" and self.settings.grey_talon_lock_enabled and self.settings.grey_talon_lock > 0:
            if self.input.key_down(self.settings.grey_talon_key):
                self.force_aim_until = max(self.force_aim_until, now + self.settings.grey_talon_lock)
                logger.debug("Grey Talon ability lock triggered; holding until %.2f", self.force_aim_until)        
        elif hero.name == "Yamato" and self.settings.yamato_lock_enabled and self.settings.yamato_lock > 0:
            if self.input.key_down(self.settings.yamato_key):
                self.force_aim_until = max(self.force_aim_until, now + self.settings.yamato_lock)
                logger.debug("Yamato ability lock triggered; holding until %.2f", self.force_aim_until)
        elif hero.name == "Vindicta" and self.settings.vindicta_lock_enabled and self.settings.vindicta_lock > 0:
            if self.input.key_down(self.settings.vindicta_key):
                self.force_aim_until = max(self.force_aim_until, now + self.settings.vindicta_lock)
                logger.debug("Vindicta ability lock triggered; holding until %.2f", self.force_aim_until)
        elif hero.name == "Paradox" and self.settings.paradox_shortcut_enabled:
            self._handle_paradox_shortcut(now)

    def _handle_paradox_shortcut(self, now: float) -> None:
        """Trigger Paradox ``E`` after ``R`` is pressed."""
        if self.input.key_down(self.settings.paradox_r_key):
            if not self._paradox_r_held:
                self._paradox_r_held = True
                self._paradox_next_e = now + 0.05
        else:
            self._paradox_r_held = False

        if self._paradox_next_e and now >= self._paradox_next_e:
            self.input.tap_key(self.settings.paradox_e_key)
            logger.debug("Paradox shortcut triggered")
            self._paradox_next_e = 0.0

    def _select_zone(self) -> str:
        """Choose a zone according to its weight, holding the choice briefly."""
        now = time.monotonic()
        if self._zone_cache is None or now - self._zone_cache_time >= self._zone_cache_interval:
            self._zone_cache = random.choices(
                list(self._zone_weights), weights=list(self._zone_weights.values()), k=1
            )[0]
            self._zone_cache_time = now
        return self._zone_cache

    def _target_position(
        self, target: dict, bone_index: int | None, zone: str = "body"
    ) -> tuple[float, float, float]:
        """Use a plausible bone or an unverified height estimate for the chosen zone."""
        centre = target["position"]
        # Player position is currently origin + 70; these estimates are not hitboxes.
        height_delta = {"head": 60, "body": 0, "legs": -40}[zone]
        fallback = (centre[0], centre[1], centre[2] + height_delta)
        try:
            if bone_index is None:
                raise ValueError(f"no {zone} bone index")
            bone_array = self.mem.read_longlong(target["node"] + mo.BONE_ARRAY)
            if not bone_array:
                raise ValueError("null bone array")
            address = bone_array + bone_index * mo.BONE_STEP
            bone = tuple(self.mem.read_float(address + offset) for offset in (0, 4, 8))
            # This bound is only a sanity check, not proof that the bone is correct.
            if (not all(math.isfinite(value) for value in bone)
                    or bone == (0.0, 0.0, 0.0) or math.dist(bone, fallback) > 150):
                raise ValueError("implausible bone position")
            return bone
        except (OSError, OverflowError, ValueError) as exc:
            now = time.monotonic()
            if now - self._last_bad_bone_warning >= 5:
                logger.warning(
                    "Bone data unavailable or implausible (%s); using approximate %s height. "
                    "Hit zones and offsets are not validated.", exc, zone
                )
                self._last_bad_bone_warning = now
            return fallback

    def pause(self) -> None:
        """Pause the aimbot."""
        self.paused = True
        logger.info("Aimbot paused")
    
    def resume(self) -> None:
        """Resume the aimbot."""
        self.paused = False
        logger.info("Aimbot resumed")
    
    def stop(self) -> None:
        """Request the aimbot to stop."""
        self.stop_requested = True
        logger.info("Aimbot stop requested")

    def run(self) -> None:
        """Main aimbot loop."""

        logger.info("Aimbot loop started - hold the left mouse button to aim")
        log_state_changes = False
        prev_locked = None
        hold_down_left_click = False
        waiting_for_local_player = False
        last_no_target_warning = float("-inf")
        try:
            active = self.input.button_down(1) or time.time() < self.force_aim_until
            while not self.stop_requested:
                try:
                    # Check if paused
                    if self.paused:
                        if hold_down_left_click:
                            self.input.button_event(1, False)
                            hold_down_left_click = False
                        time.sleep(0.1)
                        continue

                    try:
                        my_data = self.mem.read_entity(0)
                    except (EntityUnavailable, OSError) as exc:
                        # Never aim or keep synthetic input held with invalid local data.
                        if hold_down_left_click:
                            self.input.button_event(1, False)
                            hold_down_left_click = False
                        if self.locked_on is not None:
                            self._last_lock_lost = time.time()
                        self.locked_on = None
                        prev_locked = None
                        self.force_aim_until = 0.0
                        self._zone_cache = None
                        self._paradox_next_e = 0.0
                        self._paradox_r_held = False
                        if not waiting_for_local_player:
                            logger.warning(
                                "Local player unavailable: %s. Aiming disabled; "
                                "waiting for a valid player. Enter a match or check offsets.", exc
                            )
                            waiting_for_local_player = True
                        time.sleep(0.5)
                        continue
                    if waiting_for_local_player:
                        logger.info("Local player data is available again")
                        waiting_for_local_player = False

                    if not hold_down_left_click and self.input.button_down(3):
                        hold_down_left_click = True
                        self.input.button_event(1, True)

                    if hold_down_left_click and not self.input.button_down(3):
                        hold_down_left_click = False
                        self.input.button_event(1, False)

                    if hold_down_left_click:
                        time.sleep(0.01)
                        continue

                    self._update_ability_lock(my_data["hero"])
                    my_aim_angle = my_data["aim_angle"]

                    mouse_down = self.input.button_down(1) or time.time() < self.force_aim_until
                    if not log_state_changes and not mouse_down:
                        log_state_changes = True
                        active = False
                    elif mouse_down != active:
                        active = mouse_down
                        if log_state_changes:
                            logger.info("Aimbot turned %s", "on" if active else "off")
                    if not mouse_down:
                        # Left mouse button is not held and no ability lock active
                        if self.locked_on is not None:
                            self._last_lock_lost = time.time()
                        self.locked_on = None
                        time.sleep(0.01)
                        continue

                    cam_pos = self.mem.camera_position()
                    current_yaw, current_pitch = self.mem.current_angles()

                    if self.locked_on is None:
                        target_idx = None
                        best_score = None
                        unreadable = same_team = dead = 0
                        example_error = None
                        for i in range(1, 16):
                            try:
                                data = self.mem.read_entity(i)
                            except Exception as exc:
                                unreadable += 1
                                if example_error is None:
                                    example_error = f"slot {i}: {exc}"
                                continue
                            if data["team"] == my_data["team"]:
                                same_team += 1
                                continue
                            if data["health"] <= 0:
                                dead += 1
                                continue
                            if self.settings.target_select_type == "distance":
                                dx = my_data["position"][0] - data["position"][0]
                                dy = my_data["position"][1] - data["position"][1]
                                dz = my_data["position"][2] - data["position"][2]
                                dist = (dx * dx + dy * dy + dz * dz) ** 0.5
                                if best_score is None or dist < best_score:
                                    best_score = dist
                                    target_idx = i
                            else:
                                yaw, pitch = calculate_camera_rotation(cam_pos, data["position"])
                                dyaw = min(
                                    abs(yaw - current_yaw),
                                    abs(yaw - current_yaw + 360),
                                    abs(yaw - current_yaw - 360),
                                )
                                dpitch = min(
                                    abs(-pitch - current_pitch),
                                    abs(-pitch - current_pitch + 360),
                                    abs(-pitch - current_pitch - 360),
                                )
                                score = dyaw + dpitch
                                if best_score is None or score < best_score:
                                    best_score = score
                                    target_idx = i
                        self.locked_on = target_idx
                        if self.locked_on is None:
                            now = time.monotonic()
                            if now - last_no_target_warning >= 5:
                                logger.warning(
                                    "No target found: %d unreadable slots, %d same-team, "
                                    "%d non-positive health. Example: %s. "
                                    "Run python -m deadlock.diagnostics for a read-only report.",
                                    unreadable, same_team, dead, example_error or "none",
                                )
                                last_no_target_warning = now
                        if self.locked_on is not None:
                            self._zone_cache = None
                            logger.debug("Locked on to entity %d", self.locked_on)

                    if prev_locked != self.locked_on:
                        if self.locked_on is None:
                            if prev_locked is not None:
                                logger.debug("Lost target")
                        else:
                            if prev_locked is not None:
                                logger.debug(
                                    "Changed target from %d to %d", prev_locked, self.locked_on
                                )
                        prev_locked = self.locked_on

                    if self.locked_on is None:
                        time.sleep(0.01)
                        continue

                    try:
                        target = self.mem.read_entity(self.locked_on)
                    except Exception:
                        logger.debug(
                            "Failed to read entity %s; losing target", self.locked_on
                        )
                        if self.locked_on is not None:
                            self._last_lock_lost = time.time()
                        self.locked_on = None
                        continue

                    zone = self._select_zone()
                    bone_index = {
                        "head": get_head_bone_index,
                        "body": get_body_bone_index,
                        # No verified leg indices are available yet.
                        "legs": lambda _hero: None,
                    }[zone](target["hero"])
                    target_pos = self._target_position(target, bone_index, zone)

                    # Gradually rotate the camera towards the desired angles for a
                    # slightly more human-like movement.
                    yaw, pitch = calculate_camera_rotation(cam_pos, target_pos)
                    new_yaw, new_pitch = calculate_new_camera_angles(
                        current_yaw,
                        current_pitch,
                        yaw,
                        -pitch,
                        self.settings.smooth_speed,
                    )
                    self.mem.set_angles(new_yaw, new_pitch, my_aim_angle)
                    time.sleep(0.001)
                except Exception as exc:
                    logger.exception("Aimbot loop error: %s", exc)
                    time.sleep(0.01)
            
        finally:
            try:
                if hold_down_left_click:
                    self.input.button_event(1, False)
            finally:
                self.input.close()
        logger.info("Aimbot loop ended")


def main(argv: list[str] | None = None) -> None:
    """Run the aimbot entry point.

    Parameters
    ----------
    argv:
        Optional command line arguments.  Providing ``--debug`` enables
        verbose output.
    """

    parser = argparse.ArgumentParser(description="Deadlock aimbot")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="enable debug logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ensure_up_to_date()
    mem = DeadlockMemory()
    try:
        bot = Aimbot(mem)
        bot.run()
    finally:
        mem.pm.close()


if __name__ == "__main__":
    main()
