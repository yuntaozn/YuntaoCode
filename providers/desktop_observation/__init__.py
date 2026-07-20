"""Local desktop observation provider.

This package is intentionally runtime-agnostic.  YuntaoCode consumes it through
a thin adapter in ``runtime.skills.desktop``.
"""

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

