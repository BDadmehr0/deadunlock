"""Linux process discovery and memory access for the Proton game process."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass(frozen=True)
class Mapping:
    """One file-backed mapping in a process address space."""

    start: int
    end: int
    offset: int
    permissions: str
    path: str


def find_process(name: str) -> int:
    """Find a process by executable name, including Proton's Windows name."""
    target = name.casefold()
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        try:
            info = proc.info
            names = [info.get("name") or "", info.get("exe") or ""]
            names.extend(info.get("cmdline") or [])
            if any(os.path.basename(value).casefold() == target for value in names):
                return info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    raise RuntimeError(f"Game process {name!r} not found; start Deadlock through Proton first")


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

    def mappings(self, module: str) -> list[Mapping]:
        """Return mappings belonging to a named loaded module."""
        result = []
        with open(f"/proc/{self.pid}/maps", encoding="utf-8") as maps:
            for line in maps:
                fields = line.rstrip().split(None, 5)
                if len(fields) < 6:
                    continue
                path = fields[5].removesuffix(" (deleted)")
                if Path(path).name.casefold() != module.casefold():
                    continue
                start, end = (int(value, 16) for value in fields[0].split("-"))
                result.append(Mapping(start, end, int(fields[2], 16), fields[1], path))
        if not result:
            raise RuntimeError(f"Module {module!r} not found in process {self.pid}")
        return result

    def module_base(self, module: str) -> int:
        """Return the module's load base from its file-backed mappings."""
        return min(mapping.start - mapping.offset for mapping in self.mappings(module))

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
