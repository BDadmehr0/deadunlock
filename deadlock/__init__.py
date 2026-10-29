"""Public API for the Deadlock Linux/Proton tools.

Components are imported lazily so command-line modules and the offset scanner
can run without importing the GUI or input backends prematurely.
"""

from importlib import import_module

__all__ = ["DeadlockMemory", "Aimbot", "AimbotSettings", "HeroIds", "ESP"]

_MODULES = {
    "DeadlockMemory": ".memory",
    "Aimbot": ".aimbot",
    "AimbotSettings": ".aimbot",
    "HeroIds": ".heroes",
    "ESP": ".esp",
}


def __getattr__(name: str):
    """Load public components on first access."""
    if name not in _MODULES:
        raise AttributeError(name)
    return getattr(import_module(_MODULES[name], __name__), name)
