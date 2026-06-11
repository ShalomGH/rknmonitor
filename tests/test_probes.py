import pytest
from rknmon.probes.http_probe import probe_http
from rknmon.probes.dns_probe import probe_dns


class TestHttpProbe:
    @pytest.mark.asyncio
    async def test_probe_unreachable_domain(self):
        result = await probe_http("http://this-domain-does-not-exist-12345.local")
        assert result["reachable"] is False
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_probe_google(self):
        result = await probe_http("https://dns.google/resolve")
        assert result["reachable"] is True
        assert result["status_code"] is not None
        assert result["response_time_ms"] is not None
        assert result["body_hash"] is not None


class TestDnsProbe:
    @pytest.mark.asyncio
    async def test_probe_dns_exists(self):
        result = await probe_dns("google.com")
        assert result["domain"] == "google.com"
        assert len(result["results"]) >= 2  # system + at least one resolver
        assert not result["nxdomain"]

    @pytest.mark.asyncio
    async def test_probe_dns_nxdomain(self):
        result = await probe_dns("this-domain-does-not-exist-12345.local")
        # nxdomain or error expected from at least one resolver
        assert result["nxdomain"] or any(r.get("error") for r in result["results"])
