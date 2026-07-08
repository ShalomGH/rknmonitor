from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path
from typing import Awaitable, Callable


class FailureArtifactCollector:
    """Keep packet/path artifacts only for failed controlled experiments.

    Collection is disabled by default. tcpdump normally requires elevated
    privileges/capabilities; missing tools are treated as "no artifact", never
    as a probe failure.
    """

    def __init__(
        self,
        *,
        base_dir: str,
        capture_on_anomaly: bool = False,
        trace_on_anomaly: bool = False,
    ):
        self.base_dir = Path(base_dir)
        self.capture_on_anomaly = capture_on_anomaly
        self.trace_on_anomaly = trace_on_anomaly

    async def run(
        self,
        *,
        experiment_id: str,
        host: str,
        port: int,
        probe: Callable[[], Awaitable[dict]],
    ) -> dict:
        capture_proc = None
        capture_path: Path | None = None

        if self.capture_on_anomaly and shutil.which("tcpdump"):
            try:
                capture_path = self._path(experiment_id, "capture.pcap")
                capture_proc = await asyncio.create_subprocess_exec(
                    "tcpdump",
                    "-U",
                    "-n",
                    "-s",
                    "0",
                    "-w",
                    str(capture_path),
                    "host",
                    host,
                    "and",
                    "port",
                    str(port),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.sleep(0.05)
            except Exception:
                capture_proc = None
                capture_path = None

        result = await probe()

        if capture_proc is not None:
            capture_proc.terminate()
            try:
                await asyncio.wait_for(capture_proc.wait(), timeout=2)
            except Exception:
                capture_proc.kill()
                await capture_proc.wait()

        details = result.setdefault("details", {})
        details["experiment_id"] = experiment_id
        artifacts = details.setdefault("artifacts", [])

        if result.get("ok"):
            if capture_path and capture_path.exists():
                capture_path.unlink(missing_ok=True)
            return result

        if capture_path and capture_path.exists() and capture_path.stat().st_size > 0:
            artifacts.append(self._metadata(capture_path, "anomaly", "pcap"))

        if self.trace_on_anomaly:
            trace = await self._collect_trace(experiment_id, host)
            if trace:
                artifacts.append(trace)

        return result

    def _path(self, experiment_id: str, filename: str) -> Path:
        path = self.base_dir / experiment_id / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _metadata(self, path: Path, reason: str, artifact_type: str) -> dict:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "artifact_type": artifact_type,
            "reason": reason,
            "path": str(path),
            "sha256": digest,
            "size_bytes": path.stat().st_size,
        }

    async def _collect_trace(self, experiment_id: str, host: str) -> dict | None:
        if shutil.which("tracepath"):
            cmd = ["tracepath", "-n", host]
        elif shutil.which("traceroute"):
            cmd = ["traceroute", "-n", "-w", "1", "-q", "1", host]
        else:
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            path = self._path(experiment_id, "path-trace.txt")
            path.write_bytes(stdout[:1024 * 1024])
            return self._metadata(path, "anomaly", "path_trace")
        except Exception:
            return None
