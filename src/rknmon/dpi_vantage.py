from __future__ import annotations

from typing import Any


def adjust_hypothesis_with_vantage(
    details: dict[str, Any] | None,
    comparison_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Adjust a local DNS hypothesis with fresh control/external evidence.

    A reachable comparison vantage strengthens a subject-only failure. If fresh
    comparison vantages show the same DNS failure, confidence is capped because
    the evidence is more consistent with a target/resolver-wide problem.
    """
    adjusted = dict(details or {})
    if adjusted.get("hypothesis") != "dns_interference":
        return adjusted

    try:
        confidence = float(adjusted.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    evidence = [str(item) for item in adjusted.get("evidence", [])]
    summarized = [
        {
            "agent": str(row.get("agent") or "unknown"),
            "role": str(row.get("role") or "unknown"),
            "ok": bool(row.get("ok")),
            "error_type": row.get("error_type"),
        }
        for row in comparison_rows
    ]

    if any(row["ok"] for row in summarized):
        confidence = min(1.0, confidence + 0.07)
        evidence.append("fresh_control_or_external_dns_ok")
        adjusted["vantage_verdict"] = "corroborated_subject_only_failure"
    elif summarized:
        confidence = min(confidence, 0.35)
        evidence.append("fresh_control_or_external_same_failure")
        adjusted["vantage_verdict"] = "shared_failure_not_subject_specific"
    else:
        evidence.append("no_fresh_control_or_external_evidence")
        adjusted["vantage_verdict"] = "local_evidence_only"

    adjusted["confidence"] = round(confidence, 3)
    adjusted["evidence"] = sorted(set(evidence))
    adjusted["comparison_vantages"] = summarized
    return adjusted
