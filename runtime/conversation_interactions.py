from __future__ import annotations

import asyncio


pending_confirms: dict[str, asyncio.Event] = {}
confirm_responses: dict[str, str] = {}
runtime_guidance: dict[str, list[str]] = {}
