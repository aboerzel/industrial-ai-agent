# Knowledge Runtime Dependencies

`pyproject.toml` is the shared dependency contract for development, package installs
and Knowledge Docker builds. The Knowledge image installs only its service's subset,
using the project's requirements as pip constraints; it does not install Agent/API
dependencies. Python installation has no separate requirements file, lock file or
CI workflow with an independent Knowledge resolution.

Keep `transformers==5.16.1` with the image's CPU-only `torch==2.7.1+cpu` and
`torchvision==0.22.1+cpu`. Transformers 5.20.0 imports
`torch.distributed.checkpoint.hf_storage`, absent from this Torch version, during
ordinary CrossEncoder startup. The supported lower bounds in
[Transformers 5.16.1](https://github.com/huggingface/transformers/blob/v5.16.1/setup.py),
[Sentence Transformers 5.7.0](https://github.com/huggingface/sentence-transformers/blob/v5.7.0/pyproject.toml)
and [Docling IBM Models 4.0.3](https://github.com/docling-project/docling-ibm-models/blob/v4.0.3/pyproject.toml)
admit this combination. The CPU Torch/Torchvision pair follows
[PyTorch's published pairing](https://pytorch.org/get-started/previous-versions/).
Development may use a newer CUDA Torch; Transformers has the same explicit pin.
Other existing ranges remain unchanged; this is not a complete transitive lock.

## Local Model Cache

Model provisioning is separate from normal offline startup. Before an offline
deployment, provision the existing `hf-cache` volume with the configured BGE reranker,
Docling layout model and RapidOCR assets, and provision the configured embedding
model in local Ollama. No factory documents or model weights are baked into the
application image. Content comes from external read-only mounts.

RapidOCR's package-relative `models` directory is a symlink to `$HF_HOME/rapidocr`
inside the persistent cache. This keeps OCR weights across image replacements.
For RapidOCR 3.9.2's current Torch backend, this directory needs
`PP-OCRv6_det_small.pth`, `PP-OCRv6_rec_small.pth`,
`ch_ptocr_mobile_v2.0_cls_mobile.pth` and `ppocrv6_dict.txt`.
Transfer existing local artifacts from a trusted provisioned environment and retain
the library-verified SHA256 values; do not download during an offline verification.
The runtime user must be able to read the cache. An offline verification mounts it
read-only, sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and
`KNOWLEDGE_MCP_RERANKER_LOCAL_FILES_ONLY=true`, and removes cloud credentials.
RapidOCR has its own downloader, so Hugging Face flags alone do not prove offline
operation. A missing/incompatible cache must fail rather than substitute fake models.
Compose's ordinary writable cache allows explicit initial provisioning; the offline
test must use an internal network with no internet route.

## Built-Image Regression Gate

After `docker compose build --no-cache knowledge-mcp`, start a disposable container
from that immutable image using its unmodified production command and healthcheck.
Attach only an internal Docker network with disposable migrated PostgreSQL and local
Ollama. Use the application database role (no BYPASSRLS), synthetic repository data,
the read-only model/content mounts, offline flags and no cloud keys. Label the
container `industrial.knowledge-test=true`. Never point this proof at production data.

Set test-only `KNOWLEDGE_TEST_IMAGE_ID` to the image's `sha256:` ID and
`KNOWLEDGE_TEST_CONTAINER` to this disposable container, then run:

```powershell
.venv\Scripts\python.exe -m pytest tests/integration/test_knowledge_container_runtime.py -v
```

These variables configure the test harness only, not application runtime or `.env`.
KDEP-01 imports the full production composition in that image with networking disabled;
KDEP-02 instantiates real ingestion, embeddings and cross-encoder retrieval;
KDEP-03 checks actual production health and authenticated MCP readiness;
KDEP-04 retrieves an expected synthetic fixture with provenance and clearance checks;
KDEP-05 checks network isolation, credentials and offline startup logs.
Without explicit opt-in, these five deployment tests are visibly skipped in normal
deterministic gates, which must not invoke real models. Remove only the labelled
disposable containers/network afterwards; preserve shared model and application volumes.
