from dataclasses import dataclass
import platform
import sys


@dataclass(frozen=True)
class PlatformInfo:
    system: str
    python_version: str
    machine: str

    @property
    def is_windows(self) -> bool:
        return self.system == "windows"

    @property
    def is_linux(self) -> bool:
        return self.system == "linux"


def get_platform_info() -> PlatformInfo:
    raw = sys.platform.lower()
    if raw.startswith("win"):
        system = "windows"
    elif raw.startswith("linux"):
        system = "linux"
    elif raw == "darwin":
        system = "macos"
    else:
        system = raw
    return PlatformInfo(
        system=system,
        python_version=platform.python_version(),
        machine=platform.machine(),
    )
