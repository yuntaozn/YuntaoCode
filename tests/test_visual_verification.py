from runtime.visual_evidence import build_visual_evidence
from runtime.visual_verification import build_visual_verification_summary


def test_visual_verification_summarizes_visual_errors_and_model_context() -> None:
    screenshot = "D:/workspace/.tmp/preview.png"
    summary = build_visual_verification_summary(
        visual_evidence=[
            {
                "tool": "preview.capture_local_html",
                "status": "success",
                **build_visual_evidence(
                    source_type="local_html",
                    source_path="D:/workspace/index.html",
                    source_url="http://127.0.0.1:1234/index.html",
                    screenshot_path=screenshot,
                    artifact_kind="screenshot",
                    format="png",
                    width=1280,
                    height=720,
                    has_runtime_errors=True,
                    console_errors=[{"text": "module failed"}],
                    failed_requests=[{"url": "/missing.js"}],
                ),
            }
        ],
        debug_sessions=[
            {
                "tool": "preview.capture_local_html",
                "source_type": "preview.capture_page",
                "command": "playwright capture http://127.0.0.1:1234/index.html",
                "status": "success",
                "has_runtime_errors": False,
                "diagnostic_count": 1,
            }
        ],
        visual_context=[
            {
                "tool": "preview.capture_local_html",
                "source_type": "local_html",
                "path": screenshot,
                "artifact_kind": "screenshot",
                "format": "png",
                "width": 1280,
                "height": 720,
                "model_context_eligible": True,
                "injected_into_model_context": True,
            }
        ],
        verification_evidence=[
            {
                "tool": "preview.capture_local_html",
                "path": screenshot,
                "strength": "none",
                "sufficient": False,
                "modalities": ["visual"],
            }
        ],
        required_modalities=["visual"],
        observed_modalities=[],
        missing_modalities=["visual"],
        result_status="partial",
        risks=["visual_verification_not_observed"],
    )

    assert summary["schema_version"] == "visual_verification.v1"
    assert summary["boundary"] == "evidence_only"
    assert summary["counts"]["visual_evidence"] == 1
    assert summary["counts"]["visual_verification_records"] == 1
    assert summary["counts"]["debug_sessions"] == 1
    assert summary["counts"]["model_context_records"] == 1
    assert summary["counts"]["model_context_injected"] == 1
    assert summary["counts"]["runtime_error_records"] == 1
    assert summary["counts"]["console_errors"] == 1
    assert summary["counts"]["failed_requests"] == 1
    assert summary["flags"]["visual_required"] is True
    assert summary["flags"]["visual_missing"] is True
    assert summary["flags"]["has_runtime_errors"] is True
    assert summary["flags"]["model_context_injected"] is True
    assert summary["records"][0]["injected_into_model_context"] is True


def test_visual_verification_is_evidence_only_when_empty() -> None:
    summary = build_visual_verification_summary()

    assert summary["schema_version"] == "visual_verification.v1"
    assert summary["counts"]["visual_evidence"] == 0
    assert summary["flags"]["has_visual_evidence"] is False
