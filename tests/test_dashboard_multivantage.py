from unittest.mock import AsyncMock, patch

from rknmon.api.main import app
from rknmon.config.settings import settings
from fastapi.testclient import TestClient

client = TestClient(app)


@patch("rknmon.api.probes.fetch", new_callable=AsyncMock)
def test_latest_probes_can_filter_by_probe_node(mock_fetch):
    mock_fetch.return_value = [
        {"target_id": 1, "probe_node_id": 7, "probe_type": "http", "domain": "youtube.com"}
    ]

    response = client.get("/probes/latest?probe_node_id=7", headers={"X-API-Key": settings.api_key})

    assert response.status_code == 200
    assert response.json()[0]["probe_node_id"] == 7
    sql = mock_fetch.await_args.args[0]
    assert "probe_node_id = $1" in sql or "probe_node_id = $2" in sql
