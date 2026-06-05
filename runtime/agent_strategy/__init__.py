"""Agent strategy modules extracted from the conversation runner.

This package contains stateless functions that drive the agent's decision-making:

- ``classifiers``: intent classification, tool categorization, tool-call processing
- ``capability_router``: capability contracts and model-first route proposals
- ``context_hygiene``: model-context cleanup before execution
- ``profiles``: internal assistant profiles and stage presets
- ``policy``: request routing and deterministic planning gates
- ``prompts``: prompt construction for each execution stage
- ``task_contract``: model task contracts plus runtime-owned hard constraints
- ``tool_result_risks``: non-blocking, model-facing risk evidence from tool results
- ``plan_tracker``: execution plan lifecycle management
"""
