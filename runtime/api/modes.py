"""GET /modes — compatibility endpoint for the unified terminal profile.

The product no longer exposes multiple assistant modes. This endpoint remains
for older UI/runtime callers and returns the single terminal profile.
"""

from __future__ import annotations

from .base import ApiHandler
from runtime.assistant_modes import list_modes_public


class ModesHandler(ApiHandler):
    def get(self) -> None:
        self.finish_json({
            "success": True,
            "data": list_modes_public(self.get_lang()),
        })
