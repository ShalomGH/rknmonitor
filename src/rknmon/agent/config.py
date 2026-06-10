from pydantic_settings import BaseSettings


class AgentSettings(BaseSettings):
    central_api_url: str
    node_api_key: str
    agent_name: str = "rknmon-agent"
    agent_location: str | None = None
    agent_provider: str | None = None
    agent_version: str = "0.1.0"
    public_ip: str | None = None
    probe_interval_seconds: int = 300
    probe_concurrency: int = 20
    xray_enabled: bool = False
    xray_subscription_urls: str = ""
    xray_subscription_names: str = ""
    xray_test_url: str = "https://cp.cloudflare.com/"
    xray_socks_start_port: int = 11001
    xray_config_path: str = "/config/xray.generated.json"
    xray_wait_for_socks: bool = False
    xray_ready_timeout_seconds: int = 60
    dpi_enabled: bool = False
    dpi_targets: str = (
        "YouTube=www.youtube.com,Discord=discord.com,Telegram=api.telegram.org,"
        "GitHub=github.com,Cloudflare=cloudflare.com"
    )
    dpi_whitelisted_urls: str = "https://ya.ru/,https://vk.ru/,https://max.ru/"
    dpi_regular_urls: str = "https://github.com/,https://www.google.com/,https://ru.wikipedia.org/"
    dpi_timeout_seconds: float = 10.0
    dpi_l4_payload_bytes: int = 65536
    log_level: str = "INFO"

    model_config = {"env_file": ".env.agent", "extra": "ignore"}

    @property
    def xray_subscription_url_list(self) -> list[str]:
        return [u.strip() for u in self.xray_subscription_urls.split(",") if u.strip()]

    @property
    def xray_subscription_name_list(self) -> list[str]:
        return [n.strip() for n in self.xray_subscription_names.split(",") if n.strip()]

    @property
    def dpi_target_list(self) -> list[str]:
        return [t.strip() for t in self.dpi_targets.split(",") if t.strip()]

    @property
    def dpi_whitelisted_url_list(self) -> list[str]:
        return [u.strip() for u in self.dpi_whitelisted_urls.split(",") if u.strip()]

    @property
    def dpi_regular_url_list(self) -> list[str]:
        return [u.strip() for u in self.dpi_regular_urls.split(",") if u.strip()]
