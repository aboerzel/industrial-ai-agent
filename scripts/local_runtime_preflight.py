"""Strict local-provider preflight with unchanged application/provider policy."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict
from pathlib import Path

import httpx
from dotenv import load_dotenv

from industrial_ai_agent.agent.llm import LLMProviderError, LLMRequest, ModelId
from industrial_ai_agent.agent.model_egress import EgressCheckedLLMClient
from industrial_ai_agent.agent.model_selection import (
    AGENT_CONSUMER,
    CapabilityCheckedLLMClient,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.llm.configuration import load_model_catalog
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.ollama_embedding_client import (
    OllamaEmbeddingClient,
)
from scripts.local_provider_evidence import retain_native
from scripts.release_contract import PreflightEvidence, WarmMeasurement
from scripts.release_support import ROOT

PAYLOAD_HASH = "e22b8b72d7a1bcfbdda5ae37a1bbf60a3bfb30d02da6b0002a9105a782e3d9af"


def frozen_request():
    payload = json.loads(
        (ROOT / "tests/fixtures/local-runtime-preflight.json").read_text(
            encoding="utf-8"
        )
    )
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    assert hashlib.sha256(canonical).hexdigest() == PAYLOAD_HASH
    messages = []
    for item in payload["messages"]:
        row = dict(item)
        row["tool_calls"] = [
            {
                "id": call["id"],
                "name": call["function"]["name"],
                "arguments": json.loads(call["function"]["arguments"]),
            }
            for call in item.get("tool_calls", [])
        ]
        messages.append(row)
    return LLMRequest(
        messages=messages,
        tools=[t["function"] for t in payload["tools"]],
        reasoning_effort=payload["reasoning_effort"],
        max_output_tokens=payload["max_tokens"],
    )


def measure(client, label, evidence, http):
    before = http.get("http://127.0.0.1:11434/api/ps").json()["models"]
    warm = any(m["name"] == "qwen3.5:9b" for m in before)
    request = frozen_request()
    started, clock = time.time(), time.perf_counter()
    error_type, usage = None, None
    try:
        response = client.chat(ModelId("local_quality"), request)
        assert response.text or response.tool_calls, (
            "Provider returned no valid response"
        )
        usage = response.usage.model_dump() if response.usage else None
    except LLMProviderError as error:
        error_type = error.provider_error_type
    seconds, ended = time.perf_counter() - clock, time.time()
    native = retain_native(evidence, label, started, ended)
    candidates = [
        r
        for r in native["http"]
        if r["seconds"] is not None
        and abs(r["end"] - ended) < 2
        and abs((r["end"] - r["seconds"]) - started) < 2
    ]
    matched = len(candidates) == 1 and len(native["http"]) == 1
    event = candidates[0] if matched else {}
    tasks = [
        task
        for task in native["tasks"]
        if task.get("stopped")
        and started - 0.3 <= task["start"] <= ended
        and abs(task["end"] - ended) <= 2
    ]
    task = tasks[0] if len(tasks) == 1 else {}
    stopped = task.get("stopped", False)
    row = WarmMeasurement(
        seconds,
        task.get("native_tps"),
        matched,
        event.get("status"),
        warm,
        error_type,
        event.get("seconds"),
        matched,
        stopped,
    )
    (evidence / f"{label}.json").write_text(
        json.dumps(
            {
                **asdict(row),
                "start": started,
                "end": ended,
                "payload_hash": PAYLOAD_HASH,
                "usage": usage,
                "native": native,
                "models_before": before,
                "models_after": http.get("http://127.0.0.1:11434/api/ps").json()[
                    "models"
                ],
                "excluded_warmup": label == "warmup",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return row


def run_preflight(evidence: Path) -> PreflightEvidence:
    load_dotenv(ROOT / ".env", override=False)
    proof = {}
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=20) as http:
            base = os.getenv("E2E_API_URL", "http://127.0.0.1:8000")
            assert http.get(base + "/ready").status_code == 200
            # Demo mode can resolve the anonymous fallback to PUBLIC: the admin
            # endpoint then correctly denies authorization with 403, not 401.
            assert http.get(base + "/api/v1/model-assignments").status_code in {
                401,
                403,
            }
            token = os.environ["AGENT_API_MODEL_ADMIN_TOKEN"]
            headers = {"Authorization": "Bearer " + token}
            assignments = http.get(base + "/api/v1/model-assignments", headers=headers)
            assignments.raise_for_status()
            agents = [a for a in assignments.json() if a["consumer_id"] == "agent"]
            assert len(agents) == 4 and all(
                a["model_id"] == "local_quality" and a["selection_mode"] == "MANUAL"
                for a in agents
            )
            models = http.get(base + "/api/v1/models", headers=headers)
            models.raise_for_status()
            selected = next(
                m for m in models.json() if m["model_id"] == "local_quality"
            )
            assert (
                selected["provider"] == "ollama"
                and selected["provider_model"] == "qwen3.5:9b"
                and selected["execution_zone"] == "LOCAL"
            )
            configuration = load_model_catalog(
                Path(
                    os.getenv(
                        "MODEL_CATALOG_PATH", str(ROOT / "config/model_catalog.toml")
                    )
                )
            )
            model = configuration.get_model_config("local_quality")
            assert (
                model.provider == "ollama"
                and str(model.base_url) == "http://localhost:11434/v1"
                and model.provider_model == "qwen3.5:9b"
            )
            assert model.max_output_tokens == 192 and model.temperature == 0
            http.get("http://127.0.0.1:11434/api/version").raise_for_status()
            tags = http.get("http://127.0.0.1:11434/api/tags").json()["models"]
            assert {"qwen3.5:9b", "qwen3-embedding:0.6b"} <= {m["name"] for m in tags}
            shows = {}
            for name in ("qwen3.5:9b", "qwen3-embedding:0.6b"):
                response = http.post(
                    "http://127.0.0.1:11434/api/show", json={"model": name}
                )
                response.raise_for_status()
                shows[name] = response.json()
            assert shows["qwen3.5:9b"]["details"]["quantization_level"] == "Q4_K_M"
            # Ollama may inherit its runtime context rather than persist num_ctx
            # in the model tag. Effective context is always verified from /api/ps.
            context = re.search(r"num_ctx\s+(\d+)", shows["qwen3.5:9b"]["parameters"])
            assert context is None or int(context[1]) == 4096
            assert re.search(
                r"num_gpu\s+0", shows["qwen3-embedding:0.6b"]["parameters"]
            )
            loaded = http.get("http://127.0.0.1:11434/api/ps").json()["models"]
            assert all(
                m["name"] in {"qwen3.5:9b", "qwen3-embedding:0.6b"} for m in loaded
            )
            vector = OllamaEmbeddingClient().embed_query(
                "Factory Overview", classification=DataClassification.RESTRICTED
            )
            assert len(vector) >= 256
            embedding_loaded = http.get("http://127.0.0.1:11434/api/ps").json()[
                "models"
            ]
            embedding = next(
                m for m in embedding_loaded if m["name"] == "qwen3-embedding:0.6b"
            )
            assert embedding["size_vram"] == 0
            with OpenAICompatibleLLMClient(configuration) as adapter:
                client = CapabilityCheckedLLMClient(
                    EgressCheckedLLMClient(
                        adapter, configuration, DataClassification.CONFIDENTIAL
                    ),
                    configuration,
                    consumer_id=AGENT_CONSUMER,
                    data_classification=DataClassification.CONFIDENTIAL,
                )
                if not any(m["name"] == "qwen3.5:9b" for m in loaded):
                    measure(client, "warmup", evidence, http)
                measured = tuple(
                    measure(client, f"measured-{n}", evidence, http) for n in (1, 2)
                )
            loaded = http.get("http://127.0.0.1:11434/api/ps").json()["models"]
            chat = next(m for m in loaded if m["name"] == "qwen3.5:9b")
            proof = {
                "application_configuration_valid": True,
                "selected_provider": "ollama",
                "execution_zone": "LOCAL",
                "provider_model": "qwen3.5:9b",
                "application_ready": True,
                "authorization_verified": True,
                "chat_gpu": chat["size_vram"] == chat["size"]
                and chat["context_length"] == 4096,
                # CPU placement is observed immediately after actual embedding.
                # A normal later scheduler unload is not GPU placement or failure.
                "embedding_cpu": all(
                    m["size_vram"] == 0
                    for m in loaded
                    if m["name"] == "qwen3-embedding:0.6b"
                ),
                "expected_models_only": all(
                    m["name"] in {"qwen3.5:9b", "qwen3-embedding:0.6b"}
                    for m in [*embedding_loaded, *loaded]
                ),
                "measurements": measured,
            }
            (evidence / "validated-runtime-state.json").write_text(
                json.dumps(
                    {
                        "assignments": assignments.json(),
                        "selected_model": selected,
                        "loaded": loaded,
                        "embedding_loaded_after_query": embedding_loaded,
                        "model_parameters": {
                            name: s["parameters"] for name, s in shows.items()
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
    except Exception as error:  # noqa: BLE001 - unknown exceptions invalidate evidence; never skip.
        proof = {"application_errors": (type(error).__name__,)}
    result = PreflightEvidence(**proof)
    (evidence / "preflight.json").write_text(
        json.dumps({**asdict(result), **result.decision()}, indent=2), encoding="utf-8"
    )
    return result
