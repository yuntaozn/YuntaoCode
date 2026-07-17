"""Agent strategy modules extracted from the conversation runner.

This package contains stateless functions that drive the agent's decision-making:

- ``classifiers``: intent classification, tool categorization, tool-call processing
- ``capability_grounding``: runtime capability facts grounded into model task contracts
- ``capability_router``: capability contracts and model-first route proposals
- ``contract_evolution``: follow-up, runtime promotion, and contract evolution facts
- ``conversation_task_context``: follow-up task inheritance from conversation history
- ``context_hygiene``: model-context cleanup before execution
- ``document_completion``: long-form text/document completion evidence
- ``document_contract_guard``: document-export contract boundary corrections
- ``profiles``: internal assistant profiles and stage presets
- ``policy``: request routing and deterministic planning gates
- ``prompts``: prompt construction for each execution stage
- ``run_finalization``: pure run-finalization gates from observable evidence
- ``task_contract``: model task contracts plus runtime-owned safety and evidence fields
- ``tool_execution_guard``: pre-execution guard pipeline for resolved tools
- ``tool_result_risks``: non-blocking, model-facing risk evidence from tool results
- ``plan_tracker``: execution plan lifecycle management
"""
