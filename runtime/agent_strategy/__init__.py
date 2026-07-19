"""Agent strategy helpers extracted from the conversation runner.

This package keeps model-facing strategy facts separate from API and runner
plumbing.  Helpers should expose schema, evidence, prompts, and audit facts;
they should not become hidden task routers or tool-route locks.

- ``classifiers``: tool facts, protocol helpers, and progress observations
- ``capability_grounding``: normalize model-selected capability references
- ``capability_router``: capability contracts and model-first route proposals
- ``contract_evolution``: explicit model-declared continuity and success facts
- ``conversation_task_context``: bounded historical task candidates
- ``context_hygiene``: model-context cleanup before execution
- ``convergence``: progress-driven execution convergence observations
- ``document_completion``: long-form text/document completion evidence
- ``document_contract_guard``: document-export evidence advisories
- ``profiles``: internal profile descriptions without route or budget control
- ``policy``: user planning-policy gates
- ``prompts``: prompt construction for execution stages
- ``run_finalization``: pure run-finalization gates from observable evidence
- ``task_contract``: model task contracts plus runtime-owned schema boundaries
- ``tool_execution_guard``: pre-execution safety and advisory pipeline
- ``tool_result_risks``: non-blocking, model-facing risk evidence
- ``plan_tracker``: execution plan lifecycle management
"""
