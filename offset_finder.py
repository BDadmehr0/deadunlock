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

    def find(
        self,
        memory: bytes,
        base_addr: int,
        target_range: tuple[int, int] | None = None,
    ) -> int | None:
        """Return a matching target relative to the supplied memory base.

        When supplied, ``target_range`` bounds the absolute target address.
        """
        tokens = self.pattern.split()
        pattern = b"".join(
            b"." if token in ("?", "??") else re.escape(bytes([int(token, 16)]))
            for token in tokens
        )
        # Lookahead also finds overlapping occurrences of the signature.
        for match in re.finditer(b"(?=" + pattern + b")", memory, re.DOTALL):
            if match.start() + self.offset + 4 > len(memory):
                continue
            relative = struct.unpack_from("<i", memory, match.start() + self.offset)[0]
            result = match.start() + relative + self.extra
            if target_range is None or target_range[0] <= base_addr + result < target_range[1]:
                return result
        return None


def find_offsets(process_name: str = "deadlock.exe", process: LinuxProcess | None = None) -> dict[str, int]:
    """Scan readable PE image ranges, failing explicitly on missing signatures."""
    owned = process is None
    if owned:
        process = LinuxProcess(find_process(process_name))
    try:
        offsets = {}
        # The runtime only uses client.dll offsets. Do not require a schema
        # signature that no consumer reads and that may change independently.
        groups = {
            "client.dll": ["local_player_controller", "view_matrix", "entity_list", "camera_manager"],
        }
        for module, names in groups.items():
            base, image_size, mappings = process.module_image(module)
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
                        result = sig.find(data, position, (base, base + image_size))
                        if result is not None:
                            offsets[name] = position - base + result
                            logger.info("%s: %#x", name, offsets[name])
                            del pending[name]
                    position += chunk_size
            if pending:
                raise RuntimeError(
                    f"Signatures not found in {module}: {', '.join(pending)}. "
                    "The signatures may be outdated or the Proton memory layout may differ."
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
