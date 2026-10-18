"""Bounded existing Ollama/Tempo evidence; never capture prompts or credentials."""

import re
import subprocess
import time
from datetime import datetime
from pathlib import Path


def epoch(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def duration(value: str) -> float | None:
    units = {
        "h": 3600,
        "m": 60,
        "s": 1,
        "ms": 0.001,
        "µs": 1e-6,
        "us": 1e-6,
        "ns": 1e-9,
    }
    parts = re.findall(r"([\d.]+)(ms|µs|us|ns|h|m|s)", value.strip())
    return sum(float(n) * units[u] for n, u in parts) if parts else None


def native_window(start: float, end: float) -> dict:
    result = subprocess.run(
        ["docker", "logs", "--timestamps", "--tail", "100000", "ollama"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise RuntimeError("Required existing Ollama evidence unavailable")
    lines = []
    for line in (result.stdout + "\n" + result.stderr).splitlines():
        try:
            at = epoch(line.split()[0])
        except (ValueError, IndexError):
            continue
        if start - 0.3 <= at <= end + 2:
            lines.append(line)
    tasks, http = {}, []
    for line in sorted(lines):
        task = re.search(r"task\s+(\d+)\s*\|", line)
        if task:
            identifier = task[1]
            if "processing task" in line:
                tasks[identifier] = {
                    "task_id": identifier,
                    "start": epoch(line.split()[0]),
                    "progress": [],
                }
            row = tasks.get(identifier)
            if row is not None:
                match = re.search(r"task.n_tokens = (\d+)", line)
                if match:
                    row["input_tokens"] = int(match[1])
                match = re.search(
                    r"(?<!prompt )eval time =\s*([\d.]+) ms /\s*(\d+) tokens .*?([\d.]+) tokens per second",
                    line,
                )
                if match and "prompt eval time" not in line:
                    row.update(
                        generation_seconds=float(match[1]) / 1000,
                        output_tokens=int(match[2]),
                        native_tps=float(match[3]),
                    )
                match = re.search(r"n_gen =\s*(\d+), tg =\s*([\d.]+) t/s", line)
                if match:
                    row["progress"].append(
                        {
                            "at": line.split()[0],
                            "generated": int(match[1]),
                            "native_tps": float(match[2]),
                        }
                    )
                if "stop processing:" in line:
                    row["stopped"] = True
                    row["end"] = epoch(line.split()[0])
        if "[GIN]" in line and '"/v1/chat/completions"' in line:
            match = re.search(r"\|\s*(\d{3})\s*\|\s*([^|]+)\|", line)
            if match:
                http.append(
                    {
                        "end": epoch(line.split()[0]),
                        "status": int(match[1]),
                        "seconds": duration(match[2]),
                    }
                )
    return {
        "tasks": list(tasks.values()),
        "http": http,
        "lines": "\n".join(sorted(lines)),
    }


def retain_native(evidence: Path, label: str, start: float, end: float) -> dict:
    first = native_window(start, end)
    (evidence / f"{label}-ollama-first.log").write_text(
        first.pop("lines"), encoding="utf-8"
    )
    row = first
    deadline = time.monotonic() + 5
    while not row["http"] and time.monotonic() < deadline:
        time.sleep(0.2)
        row = native_window(start, end)
    lines = row.pop("lines", None)
    if lines is not None:
        (evidence / f"{label}-ollama-indexed.log").write_text(lines, encoding="utf-8")
    return row


def flatten_trace(body):
    for resource in body.get("trace", body).get(
        "resourceSpans", body.get("batches", [])
    ):
        for scope in resource.get("scopeSpans", []):
            for span in scope.get("spans", []):
                attributes = {
                    item["key"]: next(iter(item["value"].values()))
                    for item in span.get("attributes", [])
                    if item.get("value")
                }
                keep = {
                    k: v
                    for k, v in attributes.items()
                    if k.startswith(
                        (
                            "run.",
                            "model.",
                            "provider.",
                            "execution.zone",
                            "operation.",
                            "token.",
                            "request.message_count",
                            "request.tool_definition_count",
                            "request.payload_bytes",
                            "error.",
                        )
                    )
                }
                yield {
                    "name": span["name"],
                    "span_id": span["spanId"],
                    "start": int(span["startTimeUnixNano"]) / 1e9,
                    "end": int(span["endTimeUnixNano"]) / 1e9,
                    "attributes": keep,
                    "status_code": span.get("status", {}).get("code", 0),
                }


def owned_run_ids(body):
    if isinstance(body, dict):
        found = (
            {body["run_id"]}
            if isinstance(body.get("run_id"), str)
            and re.fullmatch(r"[a-f0-9-]{36}", body["run_id"])
            else set()
        )
        return found.union(*(owned_run_ids(value) for value in body.values()))
    if isinstance(body, list):
        return set().union(*(owned_run_ids(value) for value in body))
    return set()


def collect_owned_traces(client, run_ids, start, end):
    response = client.get(
        "http://127.0.0.1:3200/api/search",
        params={
            "q": '{ resource.service.name = "industrial-ai-agent" && name = "agent.run" }',
            "start": int(start) - 1,
            "end": int(end) + 2,
            "limit": 200,
        },
    )
    response.raise_for_status()
    hits = response.json()["traces"]
    if len(hits) >= 200:
        raise RuntimeError("Bounded execution trace search was truncated")
    traces = []
    for hit in hits:
        response = client.get("http://127.0.0.1:3200/api/traces/" + hit["traceID"])
        response.raise_for_status()
        spans = list(flatten_trace(response.json()))
        if any(
            s["name"] == "agent.run" and s["attributes"].get("run.id") in run_ids
            for s in spans
        ):
            traces.append(
                {
                    "trace_id": hit["traceID"],
                    "spans": [
                        s for s in spans if s["attributes"].get("run.id") in run_ids
                    ],
                }
            )
    return traces
