from runtime.visual_evidence import (
    VISUAL_EVIDENCE_SCHEMA_VERSION,
    build_visual_evidence,
    normalize_visual_evidence,
    visual_evidence_summary,
)


def test_build_visual_evidence_records_artifact_source_and_model_context() -> None:
    evidence = build_visual_evidence(
        source_type="local_html",
        source_path="D:/workspace/viewer.html",
        source_url="http://127.0.0.1:51234/viewer.html",
        screenshot_path="D:/workspace/.tmp/viewer.png",
        format="png",
        width=1440,
        height=1000,
        status_code=200,
        title="Viewer",
    )

    assert evidence["schema_version"] == VISUAL_EVIDENCE_SCHEMA_VERSION
    assert evidence["source"]["type"] == "local_html"
    assert evidence["source"]["path"] == "D:/workspace/viewer.html"
    assert evidence["artifact"]["path"].endswith("viewer.png")
    assert evidence["artifact"]["width"] == 1440
    assert evidence["page"]["status_code"] == 200
    assert evidence["runtime"]["has_errors"] is False
    assert evidence["model_context"]["eligible"] is True
    assert evidence["model_context"]["modality"] == "image"


def test_normalize_visual_evidence_accepts_legacy_screenshot_fields() -> None:
    evidence = normalize_visual_evidence({
        "type": "preview_capture",
        "source_type": "local_html",
        "source_path": "D:/workspace/viewer.html",
        "url": "http://127.0.0.1:51234/viewer.html",
        "path": "D:/workspace/preview.png",
        "artifact_kind": "screenshot",
        "format": "png",
        "has_runtime_errors": True,
        "console_errors": [{"type": "error", "text": "boom"}],
    })

    summary = visual_evidence_summary(evidence)

    assert summary is not None
    assert summary["source_type"] == "local_html"
    assert summary["path"] == "D:/workspace/preview.png"
    assert summary["has_runtime_errors"] is True
    assert summary["console_error_count"] == 1
    assert summary["model_context_eligible"] is True


def test_visual_evidence_summary_accepts_compact_summary() -> None:
    summary = visual_evidence_summary({
        "schema_version": "visual_evidence.v1",
        "kind": "visual_evidence",
        "source_type": "local_html",
        "source_url": "http://127.0.0.1:1234/index.html",
        "source_path": "D:/workspace/index.html",
        "path": "C:/Users/demo/AppData/Local/YuntaoCode/task-artifacts/run/preview/index.png",
        "artifact_kind": "screenshot",
        "format": "png",
        "width": 1440,
        "height": 1000,
        "size": 272301,
        "captured_at": "2026-07-01T15:22:54Z",
        "title": "Demo",
        "status_code": 200,
        "has_runtime_errors": False,
        "console_error_count": 0,
        "page_error_count": 0,
        "failed_request_count": 1,
        "model_context_eligible": True,
        "model_context_modality": "image",
    })

    assert summary is not None
    assert summary["source_type"] == "local_html"
    assert summary["path"].endswith("index.png")
    assert summary["width"] == 1440
    assert summary["status_code"] == 200
    assert summary["failed_request_count"] == 1
    assert summary["model_context_eligible"] is True
