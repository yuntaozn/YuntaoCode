from __future__ import annotations

import asyncio

from runtime.source_update import check_source_update

from .base import ApiHandler


class SourceUpdateHandler(ApiHandler):
    async def get(self) -> None:
        data = await asyncio.to_thread(check_source_update)
        self.finish_json({"success": True, "data": data})
