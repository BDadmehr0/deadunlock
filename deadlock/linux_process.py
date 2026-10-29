"""Linux process discovery and memory access for the Proton game process."""

from __future__ import annotations

import ntpath
import os
import struct
from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass(frozen=True)
class Mapping:
    """One mapping in a process address space; anonymous mappings have an empty path."""

    start: int
    end: int
    offset: int
    permissions: str
    path: str


def find_process(name: str) -> int:
    """Find a process by its name, executable, or command-line executable.

    Ignore later command-line arguments: Steam's reaper and other launchers
    can include the game path even though they are not the game process.
    """
    target = name.casefold()
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        try:
            info = proc.info
            cmdline = info.get("cmdline") or []
            names = [info.get("name") or "", info.get("exe") or ""]
            if cmdline:
                names.append(cmdline[0])
            if any(ntpath.basename(value).casefold() == target for value in names):
                return info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    raise RuntimeError(
        f"Game process {name!r} not found; start Deadlock through Proton first, "
        "or set DEADUNLOCK_PID to the actual game PID"
    )


class LinuxProcess:
    """Read and write another process using Linux's proc filesystem."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        try:
            self.fd = os.open(f"/proc/{pid}/mem", os.O_RDWR)
        except PermissionError as exc:
            raise PermissionError(
                f"Cannot access /proc/{pid}/mem. Check ptrace/Yama permissions; "
                "see the Linux setup instructions in README.md."
            ) from exc

    def close(self) -> None:
        """Close the process memory file."""
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __del__(self) -> None:
        if getattr(self, "fd", None) is not None:
            self.close()

    def all_mappings(self) -> list[Mapping]:
        """Return the current process mappings, including anonymous ranges."""
        result = []
        with open(f"/proc/{self.pid}/maps", encoding="utf-8") as maps:
            for line in maps:
                fields = line.rstrip().split(None, 5)
                if len(fields) < 5:
                    continue
                path = fields[5].removesuffix(" (deleted)") if len(fields) == 6 else ""
                start, end = (int(value, 16) for value in fields[0].split("-"))
                result.append(Mapping(start, end, int(fields[2], 16), fields[1], path))
        return result

    def mappings(self, module: str) -> list[Mapping]:
        """Return file-backed mappings belonging to a named loaded module."""
        result = [m for m in self.all_mappings() if Path(m.path).name.casefold() == module.casefold()]
        if not result:
            raise RuntimeError(f"Module {module!r} not found in process {self.pid}")
        return result

    def module_base(self, module: str) -> int:
        """Return the module's load base from its offset-zero header mapping."""
        mappings = self.mappings(module)
        headers = [m.start for m in mappings if m.offset == 0]
        if not headers:
            raise RuntimeError(f"Module {module!r} has no offset-zero header mapping")
        return min(headers)

    def module_image(self, module: str) -> tuple[int, int, list[Mapping]]:
        """Return a PE image's base, size, and readable mappings within its bounds.

        Proton may map PE code anonymously. Only include anonymous mappings or
        mappings of this exact module path inside the validated SizeOfImage.
        """
        maps = self.all_mappings()
        matches = [m for m in maps if Path(m.path).name.casefold() == module.casefold()]
        headers = [m for m in matches if m.offset == 0 and "r" in m.permissions]
        if len(headers) != 1:
            raise RuntimeError(f"Expected one readable header mapping for {module!r}")
        header = headers[0]
        base = header.start
        dos = self.read_bytes(base, 64)
        if dos[:2] != b"MZ":
            raise RuntimeError(f"Invalid DOS header for {module!r}")
        pe_offset = struct.unpack_from("<I", dos, 0x3c)[0]
        if not 64 <= pe_offset <= 65536:
            raise RuntimeError(f"Invalid PE header offset for {module!r}")
        pe = self.read_bytes(base + pe_offset, 84)
        if pe[:4] != b"PE\0\0" or struct.unpack_from("<H", pe, 20)[0] < 60:
            raise RuntimeError(f"Invalid PE header for {module!r}")
        magic = struct.unpack_from("<H", pe, 24)[0]
        size = struct.unpack_from("<I", pe, 80)[0]
        if magic not in (0x10b, 0x20b) or not pe_offset + 84 <= size <= 0x80000000:
            raise RuntimeError(f"Invalid PE image size or optional header for {module!r}")
        end = base + size
        regions = []
        for mapping in maps:
            anonymous = not mapping.path or mapping.path.startswith("[anon:")
            if "r" not in mapping.permissions or not (anonymous or mapping.path == header.path):
                continue
            start, stop = max(base, mapping.start), min(end, mapping.end)
            if start >= stop:
                continue
            # Adjacent readable ranges can be scanned together, including signatures
            # that straddle a file-backed/anonymous mapping boundary.
            if regions and regions[-1].end == start:
                previous = regions[-1]
                regions[-1] = Mapping(previous.start, stop, 0, "r", "")
            else:
                regions.append(Mapping(start, stop, 0, "r", ""))
        return base, size, regions

    def read_bytes(self, address: int, size: int) -> bytes:
        """Read exactly ``size`` bytes from the process."""
        data = os.pread(self.fd, size, address)
        if len(data) != size:
            raise OSError(f"Short process read at {address:#x}: {len(data)}/{size}")
        return data

    def read_int(self, address: int) -> int:
        """Read a signed 32-bit integer."""
        return struct.unpack("<i", self.read_bytes(address, 4))[0]

    def read_longlong(self, address: int) -> int:
        """Read a 64-bit pointer."""
        return struct.unpack("<Q", self.read_bytes(address, 8))[0]

    def read_float(self, address: int) -> float:
        """Read a 32-bit float."""
        return struct.unpack("<f", self.read_bytes(address, 4))[0]

    def write_float(self, address: int, value: float) -> None:
        """Write a 32-bit float."""
        data = struct.pack("<f", value)
        if os.pwrite(self.fd, data, address) != len(data):
            raise OSError(f"Short process write at {address:#x}")
