"""Run isolated, live provider/adapter contract diagnostics.

The JSON output is ephemeral. It intentionally contains only catalog metadata,
verification state, bounded diagnostics, and timings - never prompts or responses.
"""

import argparse
from pathlib import Path

from industrial_ai_agent.infrastructure.llm.configuration import load_model_catalog
from industrial_ai_agent.infrastructure.llm.provider_contract import (
    ProviderContractRunner,
)
from industrial_ai_agent.infrastructure.local_environment import load_local_environment

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the isolated Provider Contract Matrix against explicit models."
    )
    parser.add_argument(
        "--model-id",
        action="append",
        dest="model_ids",
        metavar="MODEL_ID",
        help="Stable catalog model ID. Repeat to select several models.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional ephemeral JSON output path. Do not commit this artifact.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_local_environment(PROJECT_ROOT / ".env")
    configuration = load_model_catalog(PROJECT_ROOT / "config" / "model_catalog.toml")
    model_ids = tuple(args.model_ids or (model.id for model in configuration.models))
    runner = ProviderContractRunner(configuration)
    try:
        results = runner.run(model_ids)
    finally:
        runner.close()

    output = "[\n" + ",\n".join(result.safe_json() for result in results) + "\n]\n"
    if args.output is not None:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
