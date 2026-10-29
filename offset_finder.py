"""Find offsets in Proton's loaded Windows modules via Linux process memory."""

from __future__ import annotations

import logging
import re
import struct
from dataclasses import dataclass

from deadlock.linux_process import LinuxProcess, find_process
from signature_patterns import SIGNATURES

logger = logging.getLogger(__name__)


@dataclass
class Signature:
    """RIP-relative byte pattern used to locate an address."""

    pattern: str
    offset: int
    extra: int

    def find(self, memory: bytes, base_addr: int) -> int | None:
        """Return the matched target relative to the supplied memory base."""
        tokens = self.pattern.split()
        pattern = b"".join(
            b"." if token in ("?", "??") else re.escape(bytes([int(token, 16)]))
            for token in tokens
        )
        match = re.search(pattern, memory, re.DOTALL)
        if match is None or match.start() + self.offset + 4 > len(memory):
            return None
        relative = struct.unpack_from("<i", memory, match.start() + self.offset)[0]
        return match.start() + relative + self.extra


def find_offsets(process_name: str = "deadlock.exe", process: LinuxProcess | None = None) -> dict[str, int]:
    """Scan readable module mappings, failing explicitly on missing signatures."""
    owned = process is None
    if owned:
        process = LinuxProcess(find_process(process_name))
    try:
        offsets = {}
        groups = {
            "client.dll": ["local_player_controller", "view_matrix", "entity_list", "camera_manager"],
            "schemasystem.dll": ["schema_system_interface"],
        }
        for module, names in groups.items():
            mappings = process.mappings(module)
            base = min(mapping.start - mapping.offset for mapping in mappings)
            pending = {name: Signature(*SIGNATURES[name]) for name in names}
            for mapping in mappings:
                if "r" not in mapping.permissions or not pending:
                    continue
                # Chunk the mapping and retain enough overlap for signatures at chunk boundaries.
                overlap = max(len(sig.pattern.split()) for sig in pending.values()) - 1
                chunk_size = 1024 * 1024
                position = mapping.start
                while position < mapping.end and pending:
                    size = min(chunk_size + overlap, mapping.end - position)
                    data = process.read_bytes(position, size)
                    for name, sig in list(pending.items()):
                        result = sig.find(data, position)
                        if result is not None:
                            offsets[name] = position - base + result
                            logger.info("%s: %#x", name, offsets[name])
                            del pending[name]
                    position += chunk_size
            if pending:
                raise RuntimeError(
                    f"Signatures not found in {module}: {', '.join(pending)}. "
                    "The game version or Proton memory layout may have changed."
                )
        return offsets
    finally:
        if owned:
            process.close()


def main(process_name: str = "deadlock.exe") -> None:
    """Print offsets for a running Proton game process."""
    logging.basicConfig(level=logging.INFO)
    for name, value in find_offsets(process_name).items():
        print(f"{name}: {value:#x}")


if __name__ == "__main__":
    main()
