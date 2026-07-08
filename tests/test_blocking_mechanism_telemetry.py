from rknmon.agent.experiments import infer_mechanisms, parse_experiment_target
from rknmon.custom_metrics import classify_probe_outcome


def test_parse_experiment_target_preserves_same_endpoint_fields():
    target = parse_experiment_target("control=https://example.com:8443/path?q=1")
    assert target.name == "control"
    assert target.host == "example.com"
    assert target.port == 8443
    assert target.path == "/path?q=1"


def test_infer_sni_filter_from_same_target_ab_divergence():
    rows = [
        {
            "checker": "tls-ab",
            "target": "vpn-control",
            "method": "correct",
            "ok": False,
            "error_type": "tls_timeout",
        },
        {
            "checker": "tls-ab",
            "target": "vpn-control",
            "method": "control.example",
            "ok": True,
            "error_type": None,
        },
    ]
    inferred = infer_mechanisms(rows)
    assert any(
        row["method"] == "sni_filter" and row["details"]["confidence"] >= 0.8
        for row in inferred
    )


def test_infer_host_filter_from_same_tls_ab_divergence():
    rows = [
        {
            "checker": "host-ab",
            "target": "web-control",
            "method": "correct",
            "ok": False,
            "error_type": "http_timeout",
        },
        {
            "checker": "host-ab",
            "target": "web-control",
            "method": "allowed.example",
            "ok": True,
            "error_type": None,
        },
    ]
    inferred = infer_mechanisms(rows)
    assert any(row["method"] == "http_host_filter" for row in inferred)


def test_ordinary_probe_outcomes_are_normalized():
    assert classify_probe_outcome(
        probe_type="dns", status_code=None, error=None, result={"tampered": True}
    ) == "dns_mismatch"
    assert classify_probe_outcome(
        probe_type="http", status_code=451, error=None, result={}
    ) == "http_451"
    assert classify_probe_outcome(
        probe_type="http",
        status_code=None,
        error="Connection reset by peer",
        result={},
    ) == "tcp_reset"
