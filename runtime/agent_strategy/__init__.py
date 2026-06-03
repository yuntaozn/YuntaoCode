"""Agent strategy modules extracted from the conversation runner.

This package contains stateless functions that drive the agent's decision-making:

- ``classifiers`` — intent classification, tool categorization, tool-call processing
- ``capability_router`` — capability contracts and model-first route proposals
- ``profiles``    — internal assistant profiles and stage presets
- ``policy``      — request routing and deterministic planning gates
- ``prompts``     — prompt construction for each execution stage
- ``plan_tracker``— execution plan lifecycle management
"""
