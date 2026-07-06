import argparse
import asyncio
import logging

from rknmon.agent.client import AgentClient
from rknmon.agent.config import AgentSettings
from rknmon.agent.runner import run_dpi_probe_cycle, run_probe_cycle, run_xray_probe_cycle


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rknmon-agent")
    p.add_argument("--central-api-url")
    p.add_argument("--node-api-key")
    p.add_argument("--agent-name")
    p.add_argument("--probe-interval-seconds", type=int)
    p.add_argument("--log-level")
    p.add_argument("--once", action="store_true")
    p.add_argument("--xray-only", action="store_true")
    p.add_argument("--write-xray-config", action="store_true")
    return p


async def main_async(argv=None):
    args = build_parser().parse_args(argv)
    overrides = {}
    if args.central_api_url:
        overrides["central_api_url"] = args.central_api_url
    if args.node_api_key:
        overrides["node_api_key"] = args.node_api_key
    if args.agent_name:
        overrides["agent_name"] = args.agent_name
    if args.probe_interval_seconds is not None:
        overrides["probe_interval_seconds"] = args.probe_interval_seconds
    if args.log_level:
        overrides["log_level"] = args.log_level

    settings = AgentSettings(**overrides)
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    client = AgentClient(
        settings.central_api_url,
        settings.node_api_key,
        settings.agent_name,
        agent_location=settings.agent_location,
        agent_provider=settings.agent_provider,
        agent_version=settings.agent_version,
        public_ip=settings.public_ip,
    )

    async def run_enabled_cycles() -> None:
        if settings.xray_enabled or args.xray_only:
            try:
                await run_xray_probe_cycle(
                    client,
                    subscription_urls=settings.xray_subscription_url_list,
                    subscription_names=settings.xray_subscription_name_list,
                    test_url=settings.xray_test_url,
                    socks_start_port=settings.xray_socks_start_port,
                    config_path=settings.xray_config_path if args.write_xray_config else None,
                    wait_for_socks=settings.xray_wait_for_socks or args.write_xray_config,
                    ready_timeout_seconds=settings.xray_ready_timeout_seconds,
                )
            except Exception:
                logging.exception("xray probe cycle failed")
        if settings.dpi_enabled and not args.xray_only:
            try:
                await run_dpi_probe_cycle(
                    client,
                    target_specs=settings.dpi_target_list,
                    whitelisted_urls=settings.dpi_whitelisted_url_list,
                    regular_urls=settings.dpi_regular_url_list,
                    timeout_seconds=settings.dpi_timeout_seconds,
                    l4_payload_bytes=settings.dpi_l4_payload_bytes,
                )
            except Exception:
                logging.exception("dpi probe cycle failed")
        if not args.xray_only:
            try:
                await run_probe_cycle(client)
            except Exception:
                logging.exception("target probe cycle failed")

    if args.once:
        await run_enabled_cycles()
        return

    while True:
        await run_enabled_cycles()
        await asyncio.sleep(settings.probe_interval_seconds)


def main(argv=None):
    asyncio.run(main_async(argv))


if __name__ == "__main__":
    main()
