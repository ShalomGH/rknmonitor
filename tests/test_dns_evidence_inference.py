from rknmon.agent.dns_diagnostics import classify_dns_evidence
from rknmon.agent.inference import infer_mechanisms


def test_geodns_divergence_is_not_called_interference_when_system_ip_is_reachable():
    ok, error_type, evidence = classify_dns_evidence(
        system_ips=["93.184.216.34"],
        reference_answers={
            "doh_cloudflare": ["142.250.74.14"],
            "doh_google": ["104.16.132.229"],
        },
        system_error=None,
        reference_errors={},
        tcp_reachability={
            "93.184.216.34": True,
            "142.250.74.14": True,
        },
    )

    assert ok is True
    assert error_type is None
    assert evidence["diagnosis"] == "dns_divergence_but_system_ip_reachable"


def test_dns_mismatch_requires_multiple_references_and_tcp_confirmation():
    ok, error_type, evidence = classify_dns_evidence(
        system_ips=["93.184.216.34"],
        reference_answers={
            "doh_cloudflare": ["142.250.74.14"],
            "doh_google": ["104.16.132.229"],
            "dot_cloudflare": ["142.250.74.14"],
        },
        system_error=None,
        reference_errors={},
        tcp_reachability={
            "93.184.216.34": False,
            "142.250.74.14": True,
            "104.16.132.229": True,
        },
    )

    assert ok is False
    assert error_type == "dns_mismatch_confirmed"
    assert evidence["tcp_system_reachable"] is False
    assert evidence["tcp_reference_reachable"] is True

    inferred = infer_mechanisms(
        [
            {
                "checker": "dns",
                "target": "GitHub",
                "method": "system_vs_doh_dot_tcp",
                "ok": False,
                "error_type": error_type,
                "details": evidence,
            }
        ]
    )

    assert len(inferred) == 1
    assert inferred[0]["method"] == "dns_interference"
    assert inferred[0]["details"]["confidence"] == 0.88
    assert inferred[0]["ok"] is True
    assert inferred[0]["error_type"] is None


def test_generic_system_dns_failure_is_not_promoted_to_interference():
    inferred = infer_mechanisms(
        [
            {
                "checker": "dns",
                "target": "Telegram",
                "method": "system_vs_doh_dot_tcp",
                "ok": False,
                "error_type": "dns_system_failure_unconfirmed",
                "details": {"diagnosis": "system_resolution_failure_unconfirmed"},
            }
        ]
    )

    assert inferred == []


def test_block_like_dns_answer_is_strong_evidence():
    ok, error_type, evidence = classify_dns_evidence(
        system_ips=["127.0.0.1"],
        reference_answers={
            "doh_cloudflare": ["140.82.121.4"],
            "doh_google": ["140.82.121.4"],
        },
        system_error=None,
        reference_errors={},
        tcp_reachability={"140.82.121.4": True},
    )

    assert ok is False
    assert error_type == "dns_block_ip"
    inferred = infer_mechanisms(
        [
            {
                "checker": "dns",
                "target": "GitHub",
                "ok": False,
                "error_type": error_type,
                "details": evidence,
            }
        ]
    )
    assert inferred[0]["details"]["confidence"] == 0.92
