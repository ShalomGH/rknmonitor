from __future__ import annotations
from typing import Literal

State = Literal["clear", "suspected", "blocked"]

def classify(
    http_result: dict | None,
    dns_result: dict | None,
    external_reachable: bool | None = None,
) -> tuple[State, dict]:
    """
    Rule-based classifier.
    Returns (state, details).
    """
    score = 0
    details = {}

    if dns_result:
        if dns_result.get("nxdomain"):
            score += 2
            details["dns_nxdomain"] = True
        if dns_result.get("tampered"):
            score += 2
            details["dns_tampered"] = True
        for r in dns_result.get("results", []):
            if r.get("error") and "NXDOMAIN" in str(r["error"] ):
                score += 1
                details.setdefault("dns_errors", []).append(r["error"])

    if http_result:
        if http_result.get("error") == "timeout":
            score += 2
            details["http_timeout"] = True
        elif http_result.get("error"):
            score += 1
            details["http_error"] = http_result["error"]
        status = http_result.get("status_code")
        if status in (451, 403, 402):
            score += 2
            details["http_block_status"] = status

    # External vantage confirms block
    if external_reachable is True and http_result and not http_result.get("reachable"):
        return "blocked", {**details, "external_vantage": "reachable_while_internal_not"}

    if score >= 4:
        return "blocked", details
    elif score >= 2:
        return "suspected", details
    else:
        return "clear", details
