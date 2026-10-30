"""Experimental model-name-based skeleton reads for Deadlock's Source 2 client.

Candidate layout from a third-party Windows Deadlock implementation, not verified
on the current Proton build:
https://github.com/desirably/bluelock/blob/21538018a9e1ea7430df1efe5db3eadef5024ca3/offsets/deadlock.as
https://github.com/desirably/bluelock/blob/21538018a9e1ea7430df1efe5db3eadef5024ca3/features/box_esp.as
Reading plausible data is not proof that an offset or hitbox is correct.
"""

from __future__ import annotations

import math
import struct
from collections import OrderedDict
from dataclasses import dataclass

# All addresses are candidate offsets for one third-party build, not a schema.
MODEL_STATE = 0x150
POSE_ARRAY = 0x80
MODEL_HANDLE = 0xA0
MODEL_NAMES = 0x168
MODEL_COUNT = 0x170
POSE_STRIDE = 0x20
MAX_BONES = 1024
MAX_NAME_BYTES = 64
MAX_CACHED_MODELS = 64


class SkeletonUnavailable(ValueError):
    """The candidate model layout or pose could not be validated."""


@dataclass(frozen=True)
class BoneName:
    """The index and current source pointer of one model bone name."""

    index: int
    address: int
    name: str


@dataclass(frozen=True)
class SkeletonSnapshot:
    """Named target bones and model identity from a validated candidate pose."""

    model: int
    count: int
    selected_name: str
    positions: dict[str, tuple[float, float, float]]
    indices: dict[str, int]


class SkeletonReader:
    """Resolve names per model and read the current pose without writing memory."""

    # Exact names only: e.g. head_end, eye or weapon bones are not head aliases.
    _ZONE_NAMES = {
        "head": ("head",),
        "body": ("spine_2", "spine_1", "spine_0", "pelvis"),
        "legs": ("leg_upper_l", "leg_upper_r"),
    }

    def __init__(self, mem: object) -> None:
        self.mem = mem
        self._cache: OrderedDict[tuple[int, int, int], dict[str, BoneName]] = OrderedDict()

    @staticmethod
    def _pointer(value: object, label: str) -> int:
        if type(value) is not int or not 0x10000 <= value < 0x800000000000:
            raise SkeletonUnavailable(f"invalid {label} pointer")
        return value

    def _name(self, address: int) -> str:
        """Read one bounded, null-terminated ASCII name."""
        self._pointer(address, "bone name")
        try:
            data = self.mem.pm.read_bytes(address, MAX_NAME_BYTES)
        except OSError:
            # A valid short C string can end at a mapping boundary.
            data = bytearray()
            for offset in range(MAX_NAME_BYTES):
                byte = self.mem.pm.read_bytes(address + offset, 1)
                data.extend(byte)
                if byte == b"\0":
                    break
        end = data.find(b"\0")
        if end < 1:
            raise SkeletonUnavailable("invalid or unterminated bone name")
        try:
            name = bytes(data[:end]).decode("ascii")
        except UnicodeDecodeError as exc:
            raise SkeletonUnavailable("non-ASCII bone name") from exc
        if not all(char.isalnum() or char == "_" for char in name):
            raise SkeletonUnavailable("invalid characters in bone name")
        return name.casefold()

    def _names(self, model: int, names: int, count: int) -> dict[str, BoneName]:
        key = (model, names, count)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        data = self.mem.pm.read_bytes(names, count * 8)
        pointers = struct.unpack(f"<{count}Q", data)
        found: dict[str, BoneName] = {}
        duplicates: set[str] = set()
        wanted = {name for names_for_zone in self._ZONE_NAMES.values() for name in names_for_zone}
        for index, pointer in enumerate(pointers):
            try:
                name = self._name(pointer)
            except (OSError, OverflowError, SkeletonUnavailable):
                continue
            if name in wanted:
                if name in found:
                    duplicates.add(name)
                found[name] = BoneName(index, pointer, name)
        for name in duplicates:
            found.pop(name, None)
        if "head" not in found or "pelvis" not in found:
            raise SkeletonUnavailable("model has no unique head and pelvis names")
        self._cache[key] = found
        if len(self._cache) > MAX_CACHED_MODELS:
            self._cache.popitem(last=False)
        return found

    def _position(self, array: int, index: int, origin: tuple[float, float, float]) -> tuple:
        address = array + index * POSE_STRIDE
        position = tuple(self.mem.read_float(address + offset) for offset in (0, 4, 8))
        if (not all(math.isfinite(value) for value in position)
                or position == (0.0, 0.0, 0.0) or math.dist(position, origin) > 200):
            raise SkeletonUnavailable("bone pose is zero, non-finite, or far from origin")
        return position

    def read(self, target: dict, zone: str) -> SkeletonSnapshot:
        """Read a named target pose, rejecting missing or implausible data.

        This checks candidate layout, model identity, names and rough world-space
        plausibility only. It cannot verify hitboxes or determine if the engine
        has refreshed the pose for the current animation frame.
        """
        if zone not in self._ZONE_NAMES:
            raise SkeletonUnavailable(f"unknown aim zone {zone!r}")
        try:
            scene = self._pointer(target["node"], "scene")
            centre = target["position"]
            origin = (centre[0], centre[1], centre[2] - 70)
            if not all(math.isfinite(value) for value in origin):
                raise SkeletonUnavailable("invalid scene origin")
            state = scene + MODEL_STATE
            pose = self._pointer(self.mem.read_longlong(state + POSE_ARRAY), "pose")
            handle = self._pointer(self.mem.read_longlong(state + MODEL_HANDLE), "model handle")
            model = self._pointer(self.mem.read_longlong(handle), "model")
            names = self._pointer(self.mem.read_longlong(model + MODEL_NAMES), "name array")
            count = self.mem.read_uint(model + MODEL_COUNT)
            if type(count) is not int or not 1 <= count <= MAX_BONES:
                raise SkeletonUnavailable("invalid bone count")
            key = (model, names, count)
            bones = self._names(model, names, count)
            selected = next((name for name in self._ZONE_NAMES[zone] if name in bones), None)
            if selected is None:
                raise SkeletonUnavailable(f"no recognized {zone} bone name")
            required = {"head", "pelvis", selected}
            # Recheck names/pointers even for cached models, guarding against reuse.
            for name in required:
                item = bones[name]
                if (self.mem.read_longlong(names + item.index * 8) != item.address
                        or self._name(item.address) != name):
                    self._cache.pop(key, None)
                    raise SkeletonUnavailable("model bone names changed; retry")
            positions = {name: self._position(pose, bones[name].index, origin) for name in required}
            if (self.mem.read_longlong(state + POSE_ARRAY) != pose
                    or self.mem.read_longlong(state + MODEL_HANDLE) != handle
                    or self.mem.read_longlong(handle) != model
                    or self.mem.read_longlong(model + MODEL_NAMES) != names
                    or self.mem.read_uint(model + MODEL_COUNT) != count):
                self._cache.pop(key, None)
                raise SkeletonUnavailable("model or pose changed during read; retry")
            head, pelvis = positions["head"], positions["pelvis"]
            separation = math.dist(head, pelvis)
            if not 2 <= separation <= 160 or head[2] <= pelvis[2]:
                raise SkeletonUnavailable("head/pelvis pose is implausible")
            positions["selected"] = positions[selected]
            return SkeletonSnapshot(model, count, selected, positions,
                                    {name: bones[name].index for name in required})
        except (KeyError, AttributeError, TypeError, OSError, OverflowError, struct.error) as exc:
            raise SkeletonUnavailable(f"model/pose read failed: {exc}") from exc
