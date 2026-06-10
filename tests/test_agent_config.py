from pathlib import Path

from rknmon.agent.config import AgentSettings


def test_agent_settings_from_env_file(tmp_path: Path):
    env = tmp_path / ".env.agent"
    env.write_text(
        "CENTRAL_API_URL=https://mon.example.com\n"
        "NODE_API_KEY=node-secret\n"
        "AGENT_NAME=rpi-home\n"
        "PROBE_INTERVAL_SECONDS=120\n"
        "PROBE_CONCURRENCY=7\n"
        "XRAY_ENABLED=true\n"
        "XRAY_SUBSCRIPTION_URLS=https://one.example/sub, https://two.example/sub\n"
        "XRAY_TEST_URL=https://cp.cloudflare.com/\n"
        "XRAY_SOCKS_START_PORT=12001\n"
        "XRAY_CONFIG_PATH=/tmp/xray.generated.json\n"
        "XRAY_WAIT_FOR_SOCKS=true\n"
        "XRAY_READY_TIMEOUT_SECONDS=45\n"
        "LOG_LEVEL=DEBUG\n"
    )

    settings = AgentSettings(_env_file=str(env))

    assert settings.central_api_url == "https://mon.example.com"
    assert settings.node_api_key == "node-secret"
    assert settings.agent_name == "rpi-home"
    assert settings.probe_interval_seconds == 120
    assert settings.probe_concurrency == 7
    assert settings.xray_enabled is True
    assert settings.xray_subscription_url_list == ["https://one.example/sub", "https://two.example/sub"]
    assert settings.xray_test_url == "https://cp.cloudflare.com/"
    assert settings.xray_socks_start_port == 12001
    assert settings.xray_config_path == "/tmp/xray.generated.json"
    assert settings.xray_wait_for_socks is True
    assert settings.xray_ready_timeout_seconds == 45
    assert settings.log_level == "DEBUG"
