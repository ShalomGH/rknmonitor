from pathlib import Path


def test_agent_compose_defines_xray_sidecar_and_shared_network_namespace():
    compose = Path("docker-compose.agent.yml").read_text()

    assert "rknmon-xray:" in compose
    assert "teddysun/xray" in compose
    assert "network_mode: service:rknmon-xray" in compose
    assert "xray-config:/config" in compose
    assert "until [ -s /config/xray.generated.json ]" in compose


def test_agent_compose_uses_xray_enabled_start_flow():
    compose = Path("docker-compose.agent.yml").read_text()

    assert "--write-xray-config" in compose
    assert "XRAY_ENABLED" in compose
    assert "depends_on:" in compose
    assert "rknmon-xray:" in compose


def test_agent_dockerfile_installs_curl_for_proxy_probes():
    dockerfile = Path("Dockerfile.agent").read_text()

    assert "curl" in dockerfile
