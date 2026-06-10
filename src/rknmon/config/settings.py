from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "rknmon"
    debug: bool = False
    log_level: str = "INFO"

    database_url: str = "postgresql://user:rknmon_dev@localhost/db"
    pool_min_size: int = 1
    pool_max_size: int = 10

    probe_concurrency: int = 50
    probe_interval_minutes: int = 10
    probe_jitter_seconds: int = 30

    event_retention_days: int = 365
    result_retention_days: int = 90

    proxy_url: str | None = None
    alert_webhook_url: str | None = None
    external_vantage_url: str | None = None
    external_vantage_api_key: str | None = None

    api_key: str = "dev-key-change-me"
    rate_limit: str = "100/minute"

    public_base_url: str = "https://monitor.example.com"
    agent_install_docker_compose_url: str = ""
    xray_socks_start_port: int = 11001
    probe_interval_seconds: int = 300

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
