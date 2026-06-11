from rknmon.probes.classifier import classify

class TestClassify:
    def test_clear(self):
        state, details = classify(
            {"reachable": True, "status_code": 200},
            {"tampered": False, "nxdomain": False, "results": []},
        )
        assert state == "clear"
        assert details == {}

    def test_blocked_by_dns_and_http(self):
        state, details = classify(
            {"reachable": False, "error": "timeout"},
            {"tampered": True, "nxdomain": True, "results": []},
        )
        assert state == "blocked"
        assert details["dns_nxdomain"] is True
        assert details["dns_tampered"] is True
        assert details["http_timeout"] is True

    def test_suspected_dns_only(self):
        state, details = classify(
            {"reachable": True, "status_code": 200},
            {"tampered": True, "nxdomain": False, "results": []},
        )
        assert state == "suspected"
        assert details["dns_tampered"] is True

    def test_suspected_by_451(self):
        state, details = classify(
            {"reachable": True, "status_code": 451},
            {"tampered": False, "nxdomain": False, "results": []},
        )
        assert state == "suspected"
        assert details["http_block_status"] == 451

    def test_blocked_451_plus_dns_nxdomain(self):
        state, details = classify(
            {"reachable": True, "status_code": 451},
            {"tampered": False, "nxdomain": True, "results": []},
        )
        assert state == "blocked"
        assert details["http_block_status"] == 451
        assert details["dns_nxdomain"] is True

    def test_external_vantage_confirms_block(self):
        state, details = classify(
            {"reachable": False, "error": "timeout"},
            {"tampered": False, "nxdomain": False, "results": []},
            external_reachable=True,
        )
        assert state == "blocked"
        assert details["external_vantage"] == "reachable_while_internal_not"
