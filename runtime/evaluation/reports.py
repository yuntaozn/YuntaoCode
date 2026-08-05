"""比较 Fixture 与单个 RunEvidence 视图的评测报告。

报告只是本地证据比较，不执行 Replay、不调用模型、不执行工具，也不提升能力。
目标是在自动评测 Runner 出现前，使选定回归样本已经具有实际用途。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from runtime.run_evidence import build_run_evidence


EVALUATION_REPORT_SCHEMA_VERSION = "evaluation_report.v1"

_STRENGTH_RANKS = {
    "": 0,
    "none": 0,
    "weak": 1,
    "standard": 2,
    "strong": 3,
}


def build_evaluation_report(
    fixture: dict[str, Any],
    evidence: dict[str, Any],
    *,
    report_id: str = "",
) -> dict[str, Any]:
    """比较一个评测夹具与一个已观察 RunEvidence 视图。"""
    fixture_payload = _fixture_payload(fixture)
    evidence_payload = evidence if isinstance(evidence, dict) else {}
    observed_run = evidence_payload.get("run") if isinstance(evidence_payload.get("run"), dict) else {}
    fixture_id = str(fixture_payload.get("id") or "")
    evaluated_run_id = str(observed_run.get("id") or "")
    resolved_report_id = report_id or _report_id(fixture_id, evaluated_run_id)

    if not fixture_payload:
        return _blocked_report(
            report_id=resolved_report_id,
            fixture_id=fixture_id,
            evaluated_run_id=evaluated_run_id,
            reason="fixture is missing or not an evaluation_fixture.v1 payload",
        )
    if not evidence_payload:
        return _blocked_report(
            report_id=resolved_report_id,
            fixture_id=fixture_id,
            evaluated_run_id=evaluated_run_id,
            reason="run evidence is missing",
        )

    expected = fixture_payload.get("expected") if isinstance(fixture_payload.get("expected"), dict) else {}
    observed = _observed_summary(evidence_payload)
    checks = [
        _check_result_status(expected, observed),
        _check_artifacts(expected, observed),
        _check_capability_evidence(fixture_payload, observed),
        _check_verification_strength(expected, observed),
        _check_verification_modalities(expected, observed),
        _check_failure_regression(fixture_payload, observed),
        _check_risk_regression(expected, observed),
    ]
    active_checks = [check for check in checks if check["outcome"] != "skipped"]
    blocking_failures = [
        check for check in active_checks
        if check["outcome"] == "failed" and check["severity"] == "blocking"
    ]
    warning_failures = [
        check for check in active_checks
        if check["outcome"] == "failed" and check["severity"] == "warning"
    ]
    passed_count = sum(1 for check in active_checks if check["outcome"] == "passed")
    status = "passed"
    if blocking_failures:
        status = "failed"
    elif warning_failures:
        status = "partial"
    score = passed_count / len(active_checks) if active_checks else 0.0

    return {
        "schema_version": EVALUATION_REPORT_SCHEMA_VERSION,
        "kind": "evaluation_report",
        "id": resolved_report_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fixture_id": fixture_id,
        "source_run_id": str(fixture_payload.get("source_run_id") or ""),
        "evaluated_run_id": evaluated_run_id,
        "status": status,
        "score": round(score, 4),
        "summary": _summary(status, active_checks),
        "checks": checks,
        "expected": {
            "result_status": str(expected.get("result_status") or ""),
            "artifact_count": len(_dict_items(expected.get("artifacts"))),
            "required_verification_strength": str(expected.get("required_verification_strength") or ""),
            "required_verification_modalities": _string_list(expected.get("required_verification_modalities")),
            "baseline_failed_tool_count": _safe_int((fixture_payload.get("baseline") or {}).get("failed_tool_count")),
            "baseline_risks": _string_list(expected.get("risks")),
        },
        "observed": observed,
        "boundaries": {
            "local_only": True,
            "executes_replay": False,
            "calls_model": False,
            "calls_tools": False,
            "promotes_capability": False,
            "promotes_skill": False,
            "uses_run_evidence": True,
        },
    }


def build_evaluation_report_for_run(
    fixture: dict[str, Any],
    run: Any,
    *,
    report_id: str = "",
) -> dict[str, Any]:
    """先从类似 RunRecord 的值派生 RunEvidence，再构建报告。"""
    return build_evaluation_report(fixture, build_run_evidence(run), report_id=report_id)


def _blocked_report(
    *,
    report_id: str,
    fixture_id: str,
    evaluated_run_id: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": EVALUATION_REPORT_SCHEMA_VERSION,
        "kind": "evaluation_report",
        "id": report_id or "evaluation-report",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fixture_id": fixture_id,
        "source_run_id": "",
        "evaluated_run_id": evaluated_run_id,
        "status": "blocked",
        "score": 0.0,
        "summary": reason,
        "checks": [
            {
                "id": "input_payload",
                "label": "Input payload",
                "severity": "blocking",
                "outcome": "failed",
                "expected": "evaluation_fixture.v1 and run_evidence.v1",
                "observed": reason,
                "message": reason,
            }
        ],
        "expected": {},
        "observed": {},
        "boundaries": {
            "local_only": True,
            "executes_replay": False,
            "calls_model": False,
            "calls_tools": False,
            "promotes_capability": False,
            "promotes_skill": False,
            "uses_run_evidence": True,
        },
    }


def _fixture_payload(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    nested = value.get("fixture")
    if isinstance(nested, dict):
        value = nested
    if (
        value.get("schema_version") == "evaluation_fixture.v1"
        or value.get("record_kind") == "evaluation_fixture"
    ):
        return value
    return {}


def _observed_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    run = evidence.get("run") if isinstance(evidence.get("run"), dict) else {}
    result = evidence.get("result") if isinstance(evidence.get("result"), dict) else {}
    trace = evidence.get("trace") if isinstance(evidence.get("trace"), dict) else {}
    capability = (
        evidence.get("capability_evidence")
        if isinstance(evidence.get("capability_evidence"), dict)
        else {}
    )
    observed_artifacts = _observed_artifacts(evidence)
    verification_evidence = _dict_items(result.get("verification_evidence")) or _dict_items(
        evidence.get("verification_evidence")
    )
    return {
        "run_id": str(run.get("id") or ""),
        "result_status": str(result.get("status") or trace.get("result_status") or run.get("status") or ""),
        "artifacts": observed_artifacts,
        "artifact_count": len(observed_artifacts),
        "capability_ids": _unique(capability.get("observed_capability_ids")),
        "requested_capability_ids": _unique(capability.get("requested_capability_ids")),
        "observed_effects": _unique(capability.get("observed_effects")),
        "observed_roles": _unique(capability.get("observed_roles")),
        "verification_strengths": _observed_verification_strengths(result, capability),
        "verification_modalities": _observed_verification_modalities(result, verification_evidence),
        "verification_evidence_count": len(verification_evidence),
        "failed_tool_count": _safe_int(trace.get("failed_tool_count")),
        "failure_count": len(evidence.get("failures") or []),
        "risks": _string_list(evidence.get("risks") or result.get("risks")),
    }


def _check_result_status(expected: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    expected_status = str(expected.get("result_status") or "").strip()
    observed_status = str(observed.get("result_status") or "").strip()
    if not expected_status:
        return _check("result_status", "Result status", "blocking", "skipped", expected_status, observed_status)
    return _check(
        "result_status",
        "Result status",
        "blocking",
        "passed" if expected_status == observed_status else "failed",
        expected_status,
        observed_status,
    )


def _check_artifacts(expected: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    expected_artifacts = _dict_items(expected.get("artifacts"))
    observed_artifacts = _dict_items(observed.get("artifacts"))
    if not expected_artifacts:
        return _check("artifacts", "Artifacts", "blocking", "skipped", [], observed_artifacts)
    missing = [
        artifact for artifact in expected_artifacts
        if not any(_artifact_matches(artifact, candidate) for candidate in observed_artifacts)
    ]
    return _check(
        "artifacts",
        "Artifacts",
        "blocking",
        "passed" if not missing else "failed",
        expected_artifacts,
        {
            "observed": observed_artifacts[:20],
            "missing": missing,
        },
    )


def _check_capability_evidence(fixture: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    capabilities = fixture.get("capabilities") if isinstance(fixture.get("capabilities"), dict) else {}
    expected_ids = _string_list(capabilities.get("requested"))
    observed_ids = set(_string_list(observed.get("capability_ids")))
    if not expected_ids:
        return _check("capabilities", "Capability evidence", "warning", "skipped", [], sorted(observed_ids))
    missing = [item for item in expected_ids if item not in observed_ids]
    return _check(
        "capabilities",
        "Capability evidence",
        "warning",
        "passed" if not missing else "failed",
        expected_ids,
        {
            "observed": sorted(observed_ids),
            "missing": missing,
            "note": "Capability drift is a warning because another strategy can still satisfy the task.",
        },
    )


def _check_verification_strength(expected: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    required = str(expected.get("required_verification_strength") or "").strip()
    observed_strengths = _string_list(observed.get("verification_strengths"))
    if not required:
        return _check(
            "verification_strength",
            "Verification strength",
            "warning",
            "skipped",
            required,
            observed_strengths,
        )
    best = max((_strength_rank(item) for item in observed_strengths), default=0)
    outcome = "passed" if best >= _strength_rank(required) else "failed"
    return _check(
        "verification_strength",
        "Verification strength",
        "warning",
        outcome,
        required,
        observed_strengths,
    )


def _check_verification_modalities(expected: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    required = _string_list(expected.get("required_verification_modalities"))
    observed_modalities = set(_string_list(observed.get("verification_modalities")))
    if not required:
        return _check(
            "verification_modalities",
            "Verification modalities",
            "warning",
            "skipped",
            [],
            sorted(observed_modalities),
        )
    missing = [item for item in required if item not in observed_modalities]
    return _check(
        "verification_modalities",
        "Verification modalities",
        "warning",
        "passed" if not missing else "failed",
        required,
        {
            "observed": sorted(observed_modalities),
            "missing": missing,
        },
    )


def _check_failure_regression(fixture: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    baseline = fixture.get("baseline") if isinstance(fixture.get("baseline"), dict) else {}
    expected_failed = _safe_int(baseline.get("failed_tool_count"))
    observed_failed = _safe_int(observed.get("failed_tool_count"))
    return _check(
        "failure_regression",
        "Failure regression",
        "warning",
        "passed" if observed_failed <= expected_failed else "failed",
        {"failed_tool_count_at_fixture_export": expected_failed},
        {"failed_tool_count": observed_failed},
    )


def _check_risk_regression(expected: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    baseline_risks = set(_string_list(expected.get("risks")))
    observed_risks = set(_string_list(observed.get("risks")))
    new_risks = sorted(observed_risks - baseline_risks)
    if not baseline_risks and not observed_risks:
        return _check("risk_regression", "Risk regression", "warning", "skipped", [], [])
    return _check(
        "risk_regression",
        "Risk regression",
        "warning",
        "passed" if not new_risks else "failed",
        sorted(baseline_risks),
        {"observed": sorted(observed_risks), "new": new_risks},
    )


def _check(
    check_id: str,
    label: str,
    severity: str,
    outcome: str,
    expected: Any,
    observed: Any,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "severity": severity,
        "outcome": outcome,
        "expected": expected,
        "observed": observed,
    }


def _observed_artifacts(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    result = evidence.get("result") if isinstance(evidence.get("result"), dict) else {}
    capability = (
        evidence.get("capability_evidence")
        if isinstance(evidence.get("capability_evidence"), dict)
        else {}
    )
    items: list[dict[str, Any]] = []
    items.extend(_artifact_dicts(result.get("artifacts")))
    for path in _string_list(result.get("written_paths")):
        items.append({"kind": _path_artifact_kind(path), "path": path})
    for path in _string_list(result.get("target_written_paths")):
        items.append({"kind": _path_artifact_kind(path), "path": path})
    for path in _string_list(result.get("observed_written_paths")):
        items.append({"kind": _path_artifact_kind(path), "path": path})
    for path in _string_list(result.get("changed_paths")):
        items.append({"kind": _path_artifact_kind(path), "path": path})
    for artifact in _string_list(capability.get("artifacts")):
        items.append({"kind": artifact})
    if "external_state_change" in _string_list(capability.get("observed_effects")):
        items.append({"kind": "external_state"})
    for event in _dict_items(capability.get("events")):
        capabilities = _string_list(event.get("capability_ids"))
        capability_id = capabilities[0] if capabilities else ""
        for artifact in _string_list(event.get("artifacts")):
            item = {"kind": artifact}
            if capability_id:
                item["capability_id"] = capability_id
            items.append(item)
        for path in _string_list(event.get("paths")):
            item = {"kind": _path_artifact_kind(path), "path": path}
            if capability_id:
                item["capability_id"] = capability_id
            items.append(item)
    for evidence_item in _dict_items(evidence.get("verification_evidence")):
        if evidence_item.get("path"):
            items.append({
                "kind": _path_artifact_kind(str(evidence_item["path"])),
                "path": str(evidence_item["path"]),
            })
    for evidence_item in _dict_items(result.get("verification_evidence")):
        if evidence_item.get("path"):
            items.append({
                "kind": _path_artifact_kind(str(evidence_item["path"])),
                "path": str(evidence_item["path"]),
            })
    return _unique_artifacts(items)


def _artifact_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append({str(key): item[key] for key in item if item[key] not in ("", None, [])})
        elif str(item or "").strip():
            result.append({"kind": str(item)})
    return result


def _artifact_matches(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    expected_kind = str(expected.get("kind") or "").strip()
    expected_path = str(
        expected.get("path")
        or expected.get("path_hint")
        or expected.get("output_path")
        or ""
    ).strip()
    expected_capability = str(expected.get("capability_id") or "").strip()
    if expected_kind and not _kind_matches(expected_kind, observed):
        return False
    if expected_path and not _path_matches(expected_path, str(observed.get("path") or "")):
        return False
    if (
        expected_capability
        and not expected_kind
        and not expected_path
        and expected_capability != str(observed.get("capability_id") or "").strip()
    ):
        return False
    return True


def _kind_matches(expected_kind: str, observed: dict[str, Any]) -> bool:
    observed_kind = str(observed.get("kind") or "").strip()
    if expected_kind == observed_kind:
        return True
    if expected_kind in {"file", "code", "document"} and observed.get("path"):
        return True
    if expected_kind == "external_state" and observed_kind in {"external_state", "scene", "state"}:
        return True
    if expected_kind == "screenshot" and observed_kind in {"screenshot", "image", "file"}:
        return True
    return False


def _path_matches(expected: str, observed: str) -> bool:
    expected_norm = _normalize_path(expected)
    observed_norm = _normalize_path(observed)
    if not expected_norm or not observed_norm:
        return False
    if expected_norm == observed_norm:
        return True
    return observed_norm.endswith(f"/{expected_norm}") or expected_norm.endswith(f"/{observed_norm}")


def _path_artifact_kind(path: str) -> str:
    suffix = PurePosixPath(str(path).replace("\\", "/")).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "screenshot"
    if suffix in {".doc", ".docx", ".pdf", ".md", ".txt"}:
        return "document"
    if suffix:
        return "file"
    return "artifact"


def _observed_verification_strengths(result: dict[str, Any], capability: dict[str, Any]) -> list[str]:
    values: list[str] = []
    values.extend(_string_list(capability.get("verification_strengths")))
    for item in _dict_items(result.get("verification_evidence")):
        if item.get("strength"):
            values.append(str(item["strength"]))
    return _unique(values)


def _observed_verification_modalities(
    result: dict[str, Any],
    verification_evidence: list[dict[str, Any]],
) -> list[str]:
    values = _string_list(result.get("observed_verification_modalities"))
    for item in verification_evidence:
        values.extend(_string_list(item.get("modalities")))
    return _unique(values)


def _strength_rank(value: str) -> int:
    return _STRENGTH_RANKS.get(str(value or "").strip().lower(), 0)


def _summary(status: str, checks: list[dict[str, Any]]) -> str:
    if status == "passed":
        return "All active evaluation checks passed."
    failed = [check["id"] for check in checks if check["outcome"] == "failed"]
    if status == "failed":
        return f"Blocking evaluation checks failed: {', '.join(failed)}."
    if status == "partial":
        return f"Warning evaluation checks failed: {', '.join(failed)}."
    return "Evaluation could not run."


def _report_id(fixture_id: str, run_id: str) -> str:
    parts = [part for part in (fixture_id, run_id) if part]
    return "evaluation-report-" + "-".join(parts) if parts else "evaluation-report"


def _normalize_path(value: str) -> str:
    return str(value or "").strip().replace("\\", "/").strip("/").lower()


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _unique(str(item) for item in value if str(item or "").strip())


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _unique(values: Any) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _unique_artifacts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for value in values:
        item = {str(key): str(value[key]) for key in value if value[key] not in ("", None, [])}
        if not item:
            continue
        signature = tuple(sorted(item.items()))
        if signature in seen:
            continue
        seen.add(signature)
        result.append(item)
    return result
