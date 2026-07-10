from rknmon.dpi_vantage import adjust_hypothesis_with_vantage


def _details(confidence: float = 0.88) -> dict:
    return {
        "hypothesis": "dns_interference",
        "confidence": confidence,
        "evidence": ["dns_mismatch_confirmed"],
    }


def test_fresh_reachable_control_strengthens_subject_dns_hypothesis():
    adjusted = adjust_hypothesis_with_vantage(
        _details(),
        [
            {
                "agent": "control-eu",
                "role": "control",
                "ok": True,
                "error_type": None,
            }
        ],
    )

    assert adjusted["confidence"] == 0.95
    assert adjusted["vantage_verdict"] == "corroborated_subject_only_failure"
    assert "fresh_control_or_external_dns_ok" in adjusted["evidence"]


def test_same_failure_on_control_caps_confidence():
    adjusted = adjust_hypothesis_with_vantage(
        _details(0.92),
        [
            {
                "agent": "control-eu",
                "role": "control",
                "ok": False,
                "error_type": "dns_mismatch_confirmed",
            },
            {
                "agent": "external-nl",
                "role": "external",
                "ok": False,
                "error_type": "dns_mismatch_confirmed",
            },
        ],
    )

    assert adjusted["confidence"] == 0.35
    assert adjusted["vantage_verdict"] == "shared_failure_not_subject_specific"
    assert "fresh_control_or_external_same_failure" in adjusted["evidence"]


def test_missing_control_keeps_local_confidence_and_marks_evidence_gap():
    adjusted = adjust_hypothesis_with_vantage(_details(0.82), [])

    assert adjusted["confidence"] == 0.82
    assert adjusted["vantage_verdict"] == "local_evidence_only"
    assert "no_fresh_control_or_external_evidence" in adjusted["evidence"]


def test_non_dns_hypothesis_is_unchanged():
    details = {"hypothesis": "sni_filter", "confidence": 0.88, "evidence": ["ab"]}
    assert adjust_hypothesis_with_vantage(details, [{"ok": True}]) == details
