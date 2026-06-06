import pytest


def test_imports():
    from rknmon.api.main import app
    from rknmon.db import get_pool, close_pool
    from rknmon.db_schema import init_schema
    from rknmon.probes.http_probe import probe_http
    from rknmon.probes.dns_probe import probe_dns
    from rknmon.probes.orchestrator import run_all
    from rknmon.models.schemas import Target, ProbeResult, Event
    assert True


def test_settings():
    from rknmon.config.settings import settings
    assert settings.probe_concurrency == 50
    assert settings.probe_interval_minutes == 10
