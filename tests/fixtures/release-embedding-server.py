"""Deterministic embedding HTTP transport for isolated SOFTWARE KDEP only."""

import hashlib
import json
import math
import re
from http.server import BaseHTTPRequestHandler, HTTPServer


def vector(text):
    result = [0.0] * 1024
    for term in re.findall(r"[\w-]+", text.casefold()):
        index = int.from_bytes(hashlib.sha256(term.encode()).digest()[:4], "big") % len(
            result
        )
        result[index] += 1.0
    length = math.sqrt(sum(v * v for v in result)) or 1
    return [v / length for v in result]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == "/api/embed" and data["model"] == "qwen3-embedding:0.6b"
        assert (data.get("options") or {}).get("num_gpu") in {None, 0}
        inputs = data["input"]
        if isinstance(inputs, str):
            inputs = [inputs]
        body = json.dumps(
            {"model": data["model"], "embeddings": [vector(t) for t in inputs]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 11434), Handler).serve_forever()
