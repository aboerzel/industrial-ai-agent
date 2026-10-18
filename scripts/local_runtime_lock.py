"""Test-only, machine-wide local-chat reservation shared with Node entry points."""

import json
import os
import socket
import subprocess
from contextlib import contextmanager
from pathlib import Path

RUNTIME_PORT = 46233
BUSY_EXIT = 5
ROOT = Path(__file__).resolve().parents[1]


class LocalRuntimeBusy(RuntimeError):
    def __init__(self):
        super().__init__(
            "LOCAL_RUNTIME_BUSY: another local real-model qualification owns the GPU runtime."
        )


@contextmanager
def runtime_reservation(*, port=RUNTIME_PORT):
    # Never borrow a caller's environment lease for an independent Python gate.
    broker = subprocess.Popen(
        [
            "node",
            str(ROOT / "frontend/scripts/local-runtime-lock.mjs"),
            "--broker",
            str(port),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        response = json.loads(broker.stdout.readline())
        if response["status"] == "LOCAL_RUNTIME_BUSY":
            raise LocalRuntimeBusy()
        if response["status"] != "READY":
            raise RuntimeError("Runtime reservation failed")
        yield {**os.environ, "LOCAL_RUNTIME_LEASE": json.dumps(response["lease"])}
    finally:
        broker.stdin.close()
        broker.stdout.close()
        # An inherited worker connection keeps the broker alive if its controller
        # is cancelled. Never kill that broker and free an actively used GPU slot.
        try:
            broker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


@contextmanager
def runtime_worker(env):
    lease = json.loads(env["LOCAL_RUNTIME_LEASE"])
    with socket.create_connection(("127.0.0.1", lease["port"]), timeout=5) as client:
        client.sendall((json.dumps({"token": lease["token"]}) + "\n").encode())
        with client.makefile("rb") as stream:
            response = json.loads(stream.readline(4096))
        if response["status"] != "ACQUIRED":
            raise LocalRuntimeBusy()
        # An exceptional exit skips release; EOF triggers bounded broker drain.
        yield
        client.sendall(b'{"release":true}\n')
        assert client.recv(4096) == b"", "Invalid reservation release"
