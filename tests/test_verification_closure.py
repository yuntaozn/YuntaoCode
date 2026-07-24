from runtime.verification_closure import (
    build_verification_closure,
    format_verification_closure_for_model,
)


def test_verification_closure_collects_visual_debug_artifact_and_gap_facts() -> None:
    closure = build_verification_closure(
        result_status="partial",
        required_strength="standard",
        required_modalities=["visual", "behavioral"],
        observed_modalities=["visual"],
        missing_modalities=["behavioral"],
        verification_evidence=[
            {
                "tool": "preview.capture_local_html",
                "path": "preview.png",
                "strength": "standard",
                "sufficient": True,
                "modalities": ["visual"],
            }
        ],
        visual_verification={
            "kind": "visual_verification",
            "counts": {
                "visual_evidence": 1,
                "model_context_injected": 1,
                "runtime_error_records": 0,
            },
            "flags": {
                "has_visual_evidence": True,
                "model_context_injected": True,
                "has_runtime_errors": False,
            },
        },
        debug_audit={
            "kind": "debug_audit",
            "counts": {
                "debug_sessions": 1,
                "failed_sessions": 0,
                "warning_sessions": 0,
                "timed_out_sessions": 0,
            },
            "flags": {"has_debug_evidence": True},
        },
        run_artifacts=[
            {
                "kind": "run_artifact",
                "artifact_kind": "file",
                "role": "final",
                "path": "viewer.html",
                "source_tool": "filesystem.finalize_text_file",
                "can_enter_model_context": True,
                "verification_relevance": "deliverable",
            },
            {
                "kind": "run_artifact",
                "artifact_kind": "screenshot",
                "role": "screenshot",
                "path": "preview.png",
                "source_tool": "preview.capture_local_html",
                "can_enter_model_context": True,
                "verification_relevance": "verification",
            },
        ],
        risks=["verification_modality_missing"],
    )

    assert closure["schema_version"] == "verification_closure.v1"
    assert closure["boundary"] == "evidence_only"
    assert closure["modalities"]["required"] == ["visual", "behavioral"]
    assert closure["modalities"]["observed"] == ["visual"]
    assert closure["modalities"]["missing"] == ["behavioral"]
    assert closure["counts"]["verification_records"] == 1
    assert closure["counts"]["sufficient_verification_records"] == 1
    assert closure["counts"]["final_artifacts"] == 1
    assert closure["counts"]["visual_artifacts"] == 1
    assert closure["counts"]["debug_sessions"] == 1
    assert closure["flags"]["has_required_gap"] is True
    assert closure["flags"]["has_sufficient_verification"] is True
    assert closure["flags"]["visual_entered_model_context"] is True
    assert closure["source_kinds"] == [
        "verification_evidence",
        "final_artifact",
        "visual_evidence",
        "visual_model_context",
        "debug_evidence",
    ]
    assert "missing_modality:behavioral" in closure["gap_facts"]
    assert "risk:verification_modality_missing" in closure["gap_facts"]
    assert closure["artifact_paths"]["final"] == ["viewer.html"]
    assert closure["artifact_paths"]["visual"] == ["preview.png"]

    text = format_verification_closure_for_model(closure)
    assert "Verification closure facts:" in text
    assert "missing=behavioral" in text
    assert "final_artifacts=viewer.html" in text


def test_verification_closure_is_empty_but_still_evidence_only() -> None:
    closure = build_verification_closure()

    assert closure["schema_version"] == "verification_closure.v1"
    assert closure["boundary"] == "evidence_only"
    assert closure["counts"]["verification_records"] == 0
    assert closure["flags"]["has_required_gap"] is False
    assert closure["model_facts"] == ["artifacts=final:0; visual:0; log:0; model_context:0"]
