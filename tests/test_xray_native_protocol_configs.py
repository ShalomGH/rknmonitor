from rknmon.agent.xray import build_xray_config, parse_subscription_text


def test_trojan_profile_uses_one_native_xray_server():
    profiles = parse_subscription_text(
        "trojan://test-password@nl.example.test:443?security=tls&type=ws&sni=cdn.example.test#NL-Trojan"
    )

    config, _assignments = build_xray_config(profiles)

    outbound = config["outbounds"][0]
    assert outbound["protocol"] == "trojan"
    assert outbound["settings"]["servers"] == [
        {
            "address": "nl.example.test",
            "port": 443,
            "password": "test-password",
        }
    ]
    assert outbound["streamSettings"]["network"] == "ws"
    assert outbound["streamSettings"]["tlsSettings"]["serverName"] == "cdn.example.test"


def test_hysteria2_profile_uses_native_xray_hysteria_outbound():
    profiles = parse_subscription_text(
        "hy2://test-password@hy.example.test:8443?sni=cdn.example.test&insecure=1#Hysteria-2"
    )

    assert len(profiles) == 1
    assert profiles[0].protocol == "hysteria"

    config, _assignments = build_xray_config(profiles)

    outbound = config["outbounds"][0]
    assert outbound["protocol"] == "hysteria"
    assert outbound["settings"] == {
        "version": 2,
        "address": "hy.example.test",
        "port": 8443,
    }
    assert outbound["streamSettings"]["network"] == "hysteria"
    assert outbound["streamSettings"]["hysteriaSettings"] == {
        "version": 2,
        "auth": "test-password",
    }
    assert outbound["streamSettings"]["tlsSettings"] == {
        "serverName": "cdn.example.test",
    }
