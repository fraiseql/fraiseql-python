"""examples/websocket_fastapi.py streams a subscription over its WebSocket endpoint.

Building the schema (test_every_example_builds) doesn't exercise the transport,
and the example's handshake once failed inside fraiseql. The example registers
types at import, so it runs in its own process.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.examples

_ROOT = Path(__file__).resolve().parents[3]

_SUBSCRIBE = """
import json, sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path[:0] = [str(root / "examples"), str(root)]

from fastapi.testclient import TestClient

import websocket_fastapi

with (
    TestClient(websocket_fastapi.app) as client,
    client.websocket_connect("/graphql-ws", subprotocols=["graphql-transport-ws"]) as ws,
):
    ws.send_json({"type": "connection_init", "payload": {}})
    ack = ws.receive_json()
    ws.send_json(
        {"id": "1", "type": "subscribe", "payload": {"query": "subscription { taskFeed { title status } }"}}
    )
    first = ws.receive_json()
    ws.send_json({"id": "1", "type": "complete"})

print(json.dumps([ack, first]))
"""


def test_websocket_example_streams_a_task() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _SUBSCRIBE, str(_ROOT)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=_ROOT,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert json.loads(result.stdout.splitlines()[-1]) == [
        {"type": "connection_ack"},
        {
            "id": "1",
            "type": "next",
            "payload": {"data": {"taskFeed": {"title": "Task 1", "status": "pending"}}},
        },
    ]
