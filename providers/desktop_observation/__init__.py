"""本地桌面观察 Provider。

本包有意保持与 Runtime 无关；YuntaoCode 通过 ``runtime.skills.desktop`` 中的
轻量适配器使用它。"""

from .contracts import (
    DESKTOP_STATE_SCHEMA_VERSION,
    build_desktop_state,
    build_visual_evidence,
)
from .service import DesktopObservationService

__all__ = [
    "DESKTOP_STATE_SCHEMA_VERSION",
    "DesktopObservationService",
    "build_desktop_state",
    "build_visual_evidence",
]

