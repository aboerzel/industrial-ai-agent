# Local Model Capacity on an 8-GiB GPU

The supported RTX 3070 deployment keeps **`qwen3.5:9b` on GPU and
`qwen3-embedding:0.6b` on CPU**. Both use the existing 4096 runtime context;
chat remains Q4_K_M and embeddings Q8_0. Retrieval, ingestion and reranking remain
enabled. The reranker and OCR already execute on CPU.

The two GPU-resident Ollama allocations would consume about 7496 MiB before desktop
and VM GPU consumers on an 8192-MiB GPU. The measured chat median increased from
2.844 to 9.338 seconds with idle GPU embeddings, then returned to 2.856 seconds after
unload. The representative Agent flow increased from 20.20 to 105.11 seconds.
See the [diagnosis](../reviews/local-provider-vram-coresidency-diagnosis-2026-10-16.md).
CPU embedding placement avoids this persistent GPU pressure without repeatedly
swapping chat and embedding runners.

## Provision Once, Before Starting Knowledge

Ollama remains operator-managed outside the 20-service application Compose stack.
For an existing Docker Ollama container with its persistent model cache, provision
the standard local weights first, then apply the checked-in placement configuration:

```powershell
# Explicit model provisioning, separate from normal offline startup.
docker exec ollama ollama pull qwen3-embedding:0.6b
.\scripts\configure-local-embedding-cpu.ps1
docker compose up -d
```

The script accepts `-ContainerName` for another existing Docker container. It requires
the model to be cached, performs no pull, and applies
[`Modelfile.embedding-cpu`](../../config/ollama/Modelfile.embedding-cpu) with Ollama's
supported `PARAMETER num_gpu 0`. It retains the existing embedding tag required by
the application, weights, quantization, template and context defaults; only the
placement parameter changes. The model manifest digest changes accordingly.
Reapplication is idempotent. Its one-time `ollama stop` clears a previously loaded
GPU embedding instance; run provisioning before Knowledge/client work, not during
active requests. There are no per-request unload hooks or operator steps between
retrieval and chat.

For native host Ollama, the equivalent configuration is:

```powershell
ollama show qwen3-embedding:0.6b
ollama create qwen3-embedding:0.6b -f config/ollama/Modelfile.embedding-cpu
ollama stop qwen3-embedding:0.6b
```

The placement is stored with the model manifest in the existing Ollama cache/volume
and survives container/service restarts. A fresh cache requires initial provisioning.
Pulling the upstream embedding tag again replaces its local placement configuration:
reapply the script after model provisioning/updates and before starting Knowledge.
Do not change the GPU chat model to solve embedding capacity.

## Runtime Verification and Offline Startup

After a real Knowledge query and a chat request, `docker exec ollama ollama ps` must
show embeddings as **100% CPU**, chat as **100% GPU**, context 4096. `/api/ps` reports
`size_vram=0` for embeddings; that is intentional and does not indicate degraded chat.
Both models may remain resident in different memory pools. Ordinary Ollama idle
expiry still applies. Cold loading and the first Knowledge projection/index warmup
cost more than warm queries and must be measured separately.

Preserve the Ollama volume and the existing Hugging Face/Docling/OCR cache. Normal
offline startup uses cached assets, no model pulls, and the existing offline flags
described in [Knowledge runtime dependencies](knowledge-runtime-dependencies.md).
Knowledge's protocol readiness includes real initialization and advertised tools;
it must not be bypassed to hide a missing model/cache.

The SDK timeout remains **45 seconds**, Agent/API budget **90 seconds**, retries **0**.
This policy changes embedding execution placement only. It does not change model
assignments, classification, RLS, authorization, local egress restrictions, provider
cleanup or sequential Agent orchestration. CPU models remain LOCAL for all trusted
classifications; there is no external fallback. GPU chat CPU fallback is a separate
degraded deployment condition.

Global `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_KEEP_ALIVE=0` were evaluated but are
not enabled by this policy: both impose repeated load/lifecycle costs. Embedding-only
request keep-alive is not currently exposed by application composition. No adapter
changes or extra inference service are introduced.
