# Knowledge MCP Dependency Remediation — 2026-10-16

## Result and Scope

**Finding fixed: YES. Severity: MEDIUM.** This change repairs only V01,
**“Fresh Knowledge image cannot start”**, from the
[current comprehensive review](final-comprehensive-verification-and-review-2026-10-16-run-081632.md).
The original affected paths were `Dockerfile.knowledge-mcp:18`, its dependency
installation at line 24, `sentence_transformers_reranker.py:4` and Knowledge startup
composition. The historical review remains unchanged. V02 is outside this repair.

Baseline: branch `main`, HEAD `e8f7c63debcaf5f284da8186d39f290e1cff5171`, clean working
tree. Evidence is retained outside the repository at
`D:/Freelance/industrial-knowledge-dependency-fix-20261016-085327/`, including initial
tracked-file hashes, complete build logs, tracebacks, package metadata, JUnit results,
runtime probes and integrity deltas. Private disposable-test credentials remain outside
the repository and are not included here.

## Reproduction Before Changes

**PRE_FIX_REPRODUCED = YES.** A fresh `docker compose build --no-cache knowledge-mcp`
succeeded. Starting that image with the unmodified production command, offline flags
and existing local assets reproduced the fatal traceback:

```text
ModuleNotFoundError: No module named 'torch.distributed.checkpoint.hf_storage'
```

Transformers then reports that `PreTrainedModel` cannot be imported. The retained
`pre-fix-first-fatal.log` records the production traceback; KDEP-01 also failed against
the original image with networking disabled, before the dependency change was proven.

| Package | Original clean image | Final clean image |
| --- | --- | --- |
| Python | 3.12.15 | 3.12.15 |
| torch | 2.7.1+cpu | 2.7.1+cpu |
| torchvision | 0.22.1+cpu | 0.22.1+cpu |
| transformers | 5.20.0 | 5.16.1 |
| sentence-transformers | 5.7.0 | 5.7.0 |
| tokenizers | 0.23.3 | 0.23.3 |
| accelerate | 1.15.0 | 1.15.0 |
| safetensors | 0.8.0 | 0.8.0 |
| numpy | 2.5.2 | 2.5.2 |
| scikit-learn | 1.9.1 | 1.9.1 |
| docling | 2.125.0 | 2.125.0 |
| docling-core | 2.101.1 | 2.101.1 |
| docling-ibm-models | 4.0.3 | 4.0.3 |
| docling-slim | 2.125.0 | 2.125.0 |
| docling-parse | 7.22.3 | 7.22.3 |
| rapidocr | 3.9.2 | 3.9.2 |
| langchain-ollama | 1.1.0 | 1.1.0 |
| huggingface-hub | 1.33.0 | 1.33.0 |

Complete relevant requirements and original install inventory are retained in
`pre-fix-container-ml-metadata.json` and `pre-fix-all-packages-from-build.txt`;
`final-all-packages.json` records the final installed package inventory.

## Root Cause and Minimal Fix

Transformers 5.20.0 imports `HuggingFaceStorageReader` and `HuggingFaceStorageWriter`
from `torch.distributed.checkpoint.hf_storage` when its distributed-checkpoint guard
accepts Torch >=2.7. That module is absent from the intentionally pinned Torch 2.7.1
CPU wheel. Ordinary CrossEncoder initialization reaches this optional distributed
module; no distributed training is requested by the application.

`pyproject.toml` previously declared Sentence Transformers but no explicit Transformers
constraint. The Dockerfile independently repeated the service's dependency ranges and
generated constraints for Torch/Torchvision only. A clean transitive resolution therefore
selected Transformers 5.20.0. The passing host environment instead had Transformers
5.16.1 and Torch 2.14.0+cu126. No Python requirements/constraints lock file, build script
or CI workflow supplied another authoritative Knowledge resolution. This is transitive
dependency drift and an unsupported resolved combination, not a Python-version problem
or evidence of a corrupted CPU wheel.

The fix pins `transformers==5.16.1` in the shared `pyproject.toml`. Knowledge Docker
derives pip version constraints from that source, stripping installation extras while
retaining version bounds. Only the existing CPU Torch/Torchvision pair remains specific
to the image. The installed service subset stays limited to Knowledge dependencies.
The final image satisfies every active installed requirement of the recorded ML
packages. Library support and cache/test instructions are documented in
[Knowledge runtime dependencies](../learning/knowledge-runtime-dependencies.md).

No provider, agent orchestration, authorization, classification, RLS, public schema,
healthcheck or production command was changed. No import masking, monkey patch or
fake/no-op embedding fallback was introduced. No functionality was disabled.

## Offline Production Functionality

The first post-pin offline startup exposed an additional cache gap: RapidOCR's Torch
weights were stored inside the replaceable package directory. It attempted a blocked
ModelScope download and failed. This failed attempt is preserved in
`fixed-offline-first-start.log`; no model was downloaded.

The Dockerfile now links RapidOCR's `models` directory to `$HF_HOME/rapidocr` in the
existing persistent model cache. Already available local Torch OCR weights and the
recognition dictionary were copied into that cache, with SHA256 evidence retained.
Model provisioning remains separate from normal startup; no model artifacts or factory
content are baked into the application image.

A disposable container then started the actual production command on an internal Docker
network with only disposable PostgreSQL and local Ollama reachable. Content and all
model assets were mounted read-only. Hugging Face offline flags and local-only reranker
loading were enabled; cloud credentials were absent. Its application DB role was
confirmed `NOSUPERUSER NOBYPASSRLS`. The real startup warmed authorized catalog ingestion,
Torch OCR, layout processing, local embeddings and the BGE cross-encoder before MCP
readiness succeeded. Restart count remained zero.

| Regression | Actual proof | Result |
| --- | --- | --- |
| KDEP-01 | Full production imports inside clean image, network disabled | PASS |
| KDEP-02 | Real Docling ingestion, finite local embedding vector, cross-encoder retrieval | PASS |
| KDEP-03 | Unchanged Docker healthcheck and authenticated MCP protocol readiness | PASS |
| KDEP-04 | Expected `doc-s04quality09procedure`, authorized classification, source/chunk provenance; no PUBLIC disclosure | PASS |
| KDEP-05 | Internal network only, read-only cached assets, no cloud keys or startup downloads | PASS |

All five tests passed together. The final full-stack rebuild additionally passed a
network-disabled production import, recorded the same ML versions and served the same
PUBLIC/CONFIDENTIAL document retrieval through its real MCP endpoint.

## Complete Clean Stack Proof

All 20 Compose services were stopped safely with `docker compose stop`. Persistent
application, PostgreSQL, model and observability volumes were preserved. Then
`docker compose build --no-cache` rebuilt all seven project images successfully:

| Image | Build | Image ID |
| --- | --- | --- |
| factory-mcp | PASS | `sha256:0310469e73471f04d8d756f4a2422bf98459960a0887f51d3fa5c35723132cea` |
| knowledge-mcp | PASS | `sha256:2ba2d648aa6c4309f2ca8b583f270e0f5223d2e033e596f33342d02e69eae6e6` |
| hardware-mcp | PASS | `sha256:7bf40a3677ec6938e7da61c1492d4c60de4088dfad82bb1c4667d414e862f338` |
| agent-api | PASS | `sha256:264b14c6dcc7d1003037ba08e89a8f35090ef918f50d8751e0e041e7b73f3b5b` |
| observability-mcp | PASS | `sha256:28941c65c6dd36670fa30608942b2d73ec939a4150ecc2315bb5cf17b6333984` |
| runtime-mcp | PASS | `sha256:d269d92d58a2d5b555bdd4980302e48f4761a97b68a68f02f0a81d3554af7d11` |
| rca-mcp | PASS | `sha256:6d9026c82921af950c05a0a1b4c9f028cef12e5406e4ffb052e3e1e22fde5f72` |

The complete stack started from those images using the external safety override that
empties cloud-provider keys, enables offline model loading and mounts the cache read-only.
Final state: **20/20 running and healthy, zero restarts across all services**.
Knowledge authenticated protocol readiness succeeds; Agent API `/health` and `/ready`
return 200. Other MCP services and supporting HTTP readiness probes also succeed.
Health and restart counts were rechecked 185 seconds after all 20 services were first
healthy. The healthy stack
remains running; only labelled disposable test infrastructure was removed.

## Tests and Quality

| Gate | Result |
| --- | --- |
| Full backend, `pytest tests -q` | 1,963 passed, 0 failed, 6 skipped |
| INTEGRATION, repository quality gate | 278 passed, 0 failed, 5 skipped |
| KDEP deployment gate, explicit opt-in | 5 passed, 0 failed, 0 skipped |
| FAST, repository quality gate | PASS: 1,670 unit passed / 1 skipped; 294 frontend passed |
| Ruff / format | PASS; 258 Python files checked for formatting |
| Secret scan | PASS |
| Compose config / `git diff --check` | PASS |

Five normal-gate skips are the opt-in deployment tests, executed separately above.
The remaining backend skip is Windows symlink creation being unavailable. Relevant
executed scopes include Knowledge/retrieval/Docling (66 passed), embedding egress
(278), R01 (29), N01 (21), FC02 (37) and readiness (12), alongside document/API and
real PostgreSQL integration coverage. These overlapping scope counts are not additive.

Verification history is retained: the first backend invocation omitted the host
`FACTORY_DATA_ROOT` override and had one seed-test failure (1,962 passed / 6 skipped).
The corrected complete run passed. The first combined KDEP invocation encountered a
Windows log-decoding error in the new harness (4 passed / 1 failed); explicit UTF-8
subprocess decoding fixed the harness, and the complete five-test gate passed.

## Logs, Integrity and Limits

Knowledge and Agent logs contain no persistent unexpected import/runtime/model-load or
embedding error and no final startup download attempt. RapidOCR reports valid cached
files. Torch's padding-copy warning is benign and does not indicate version incompatibility.
One initial Loki readiness 503 recovered to 200; startup evidence is retained.

Only the intended four existing tracked files changed: `pyproject.toml`,
`Dockerfile.knowledge-mcp`, the Compose contract test and the retrieval-baseline guide.
New files are the five-test deployment gate, dependency guide and this protocol.
Matching German documentation remains local and Git-ignored. Historical review hashes,
application source, `.env` and `.env.example` remain unchanged; nothing is staged.

External model calls: **0**. Successful runtime downloads: **0**; the initial blocked
RapidOCR attempt was diagnosed and eliminated before the successful offline proof.
Real protected side effects: **0**. Commits/pushes/external deployments: **0**.

The current compatibility pin is deliberate; the remaining dependency ranges are not
a complete reproducibility lock. Future ML updates require rerunning the built-image
gate with provisioned local assets. V01 is fixed and this scoped change is ready to
commit. This protocol does not reclassify or repair the separate historical V02 finding.
