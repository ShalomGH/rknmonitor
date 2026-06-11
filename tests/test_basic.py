def test_imports():
    from rknmon.api.main import app
    from rknmon.db import close_pool, get_pool
    from rknmon.db_schema import init_schema
    from rknmon.models.schemas import Event, ProbeResult, Target
    from rknmon.probes.dns_probe import probe_dns
    from rknmon.probes.http_probe import probe_http
    from rknmon.probes.orchestrator import run_all

    assert app is not None
    assert get_pool is not None
    assert close_pool is not None
    assert init_schema is not None
    assert probe_http is not None
    assert probe_dns is not None
    assert run_all is not None
    assert Target is not None
    assert ProbeResult is not None
    assert Event is not None


def test_settings():
    from rknmon.config.settings import settings
    assert settings.probe_concurrency == 50
    assert settings.probe_interval_minutes == 10
