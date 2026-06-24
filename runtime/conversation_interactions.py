from __future__ import annotations

import asyncio


pending_confirms: dict[str, asyncio.Event] = {}
confirm_responses: dict[str, str] = {}
runtime_guidance: dict[str, list[str]] = {}
paused_runs: dict[str, asyncio.Event] = {}
active_run_tasks: dict[str, asyncio.Task[None]] = {}
active_stream_conversation_runs: dict[str, str] = {}
