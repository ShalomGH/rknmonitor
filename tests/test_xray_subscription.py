import base64

from rknmon.agent.xray import build_xray_config, parse_subscription_text


def test_parse_base64_subscription_extracts_xray_profile_metadata():
    link = (
        "vless://11111111-1111-1111-1111-111111111111@example.com:443"
        "?type=tcp&security=reality&sni=www.microsoft.com&fp=chrome&pbk=abc&sid=01"
        "#reality-main"
    )
    raw = base64.b64encode(link.encode()).decode()

    profiles = parse_subscription_text(raw)

    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.name == "reality-main"
    assert profile.protocol == "vless"
    assert profile.host == "example.com"
    assert profile.port == 443
    assert profile.transport == "tcp"
    assert profile.security == "reality"
    assert profile.sni == "www.microsoft.com"
    assert profile.fingerprint == "chrome"
    assert profile.raw_url == link


def test_parse_mixed_plain_subscription_supports_multiple_protocols():
    raw = "\n".join(
        [
            "trojan://secret@de.example.net:443?security=tls&type=ws&sni=cdn.example.net#trojan-ws",
            "vmess://" + base64.b64encode(
                b'{"v":"2","ps":"vmess-grpc","add":"vm.example.net","port":"443","id":"uuid","aid":"0","net":"grpc","tls":"tls","sni":"sni.example.net"}'
            ).decode(),
        ]
    )

    profiles = parse_subscription_text(raw)

    assert [p.protocol for p in profiles] == ["trojan", "vmess"]
    assert profiles[0].transport == "ws"
    assert profiles[1].name == "vmess-grpc"
    assert profiles[1].transport == "grpc"
    assert profiles[1].sni == "sni.example.net"


def test_build_xray_config_creates_one_socks_inbound_and_route_per_profile():
    profiles = parse_subscription_text(
        "\n".join(
            [
                "vless://11111111-1111-1111-1111-111111111111@example.com:443?type=tcp&security=reality&sni=www.microsoft.com&fp=chrome#ru-cascade",
                "trojan://secret@de.example.net:443?security=tls&type=ws&sni=cdn.example.net#de-direct",
            ]
        )
    )

    config, assignments = build_xray_config(profiles, socks_start_port=11001)

    assert [a["socks_port"] for a in assignments] == [11001, 11002]
    assert config["inbounds"][0]["tag"] == "in-ru-cascade"
    assert config["outbounds"][0]["tag"] == "out-ru-cascade"
    assert config["outbounds"][0]["protocol"] == "vless"
    assert "raw_url" not in config["outbounds"][0]
    assert config["outbounds"][0]["settings"]["vnext"][0]["address"] == "example.com"
    assert config["outbounds"][0]["streamSettings"]["security"] == "reality"
    assert config["outbounds"][0]["streamSettings"]["realitySettings"]["serverName"] == "www.microsoft.com"
    assert config["routing"]["rules"][0] == {
        "type": "field",
        "inboundTag": ["in-ru-cascade"],
        "outboundTag": "out-ru-cascade",
    }


def test_build_xray_config_suffixes_duplicate_profile_names_for_unique_tags():
    profiles = parse_subscription_text(
        "\n".join(
            [
                "vless://11111111-1111-1111-1111-111111111111@one.example.com:443?type=tcp&security=reality#same-name",
                "vless://22222222-2222-2222-2222-222222222222@two.example.com:443?type=tcp&security=reality#same-name",
            ]
        )
    )

    config, assignments = build_xray_config(profiles, socks_start_port=11001)

    assert [a["profile_id"] for a in assignments] == ["same-name", "same-name-2"]
    assert [i["tag"] for i in config["inbounds"]] == ["in-same-name", "in-same-name-2"]
    assert [o["tag"] for o in config["outbounds"]] == ["out-same-name", "out-same-name-2"]
