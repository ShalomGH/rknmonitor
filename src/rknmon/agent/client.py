import aiohttp


class AgentClient:
    def __init__(
        self,
        base_url: str,
        node_api_key: str,
        agent_name: str,
        agent_location: str | None = None,
        agent_provider: str | None = None,
        agent_role: str = "subject",
        agent_version: str = "0.1.0",
        public_ip: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.node_api_key = node_api_key
        self.agent_name = agent_name
        self.agent_location = agent_location
        self.agent_provider = agent_provider
        self.agent_role = agent_role
        self.agent_version = agent_version
        self.public_ip = public_ip

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Node-API-Key": self.node_api_key}

    async def register(self) -> dict:
        payload = {
            "name": self.agent_name,
            "location": self.agent_location,
            "provider": self.agent_provider,
            "role": self.agent_role,
            "agent_version": self.agent_version,
            "public_ip": self.public_ip,
        }
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.post(f"{self.base_url}/agent/register", json=payload) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def heartbeat(self) -> dict:
        payload = {"agent_version": self.agent_version, "public_ip": self.public_ip}
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.post(f"{self.base_url}/agent/heartbeat", json=payload) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def fetch_targets(self) -> list[dict]:
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.get(f"{self.base_url}/agent/targets") as resp:
                resp.raise_for_status()
                return await resp.json()

    async def submit_results(self, results: list[dict]) -> dict:
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.post(f"{self.base_url}/agent/results", json={"results": results}) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def submit_xray_results(self, results: list[dict]) -> dict:
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.post(f"{self.base_url}/agent/xray-results", json={"results": results}) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def submit_dpi_results(self, results: list[dict]) -> dict:
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.post(f"{self.base_url}/agent/dpi-results", json={"results": results}) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def submit_subscription_health(self, items: list[dict]) -> dict:
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.post(
                f"{self.base_url}/agent/subscription-health", json={"items": items}
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
