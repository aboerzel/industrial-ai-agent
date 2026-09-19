import argparse
from pathlib import Path

from industrial_ai_agent.agent.llm import (
    LLMClient,
    LLMMessage,
    LLMRequest,
    MessageRole,
    ModelId,
)
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    EgressCheckedLLMClient,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    AuthenticationMode,
    ModelCatalogConfiguration,
    load_model_catalog,
)
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.local_environment import (
    load_local_environment,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILES = ("local_fast", "local_quality")
PUBLIC_PROFILE = "groq_benchmark"
LOCAL_EXPECTED_RESPONSE = "Industrial AI Agent ready"
PUBLIC_EXPECTED_RESPONSE = "PUBLIC_LLM_OK"


def main() -> None:
    args = parse_args()
    model_ids = tuple(args.model_ids or DEFAULT_PROFILES)
    load_local_environment(PROJECT_ROOT / ".env")
    configuration = load_model_catalog(PROJECT_ROOT / "config" / "model_catalog.toml")

    with OpenAICompatibleLLMClient(configuration) as adapter:
        client = EgressCheckedLLMClient(
            adapter,
            configuration,
            DataClassification.PUBLIC,
        )
        for model_id in model_ids:
            run_model_smoke_test(client, configuration, model_id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explicitly call one or more configured catalog models."
    )
    parser.add_argument(
        "--model-id",
        action="append",
        dest="model_ids",
        metavar="MODEL_ID",
        help=(
            "Stable model ID to call. Repeat for multiple models. "
            "Defaults to local_fast and local_quality."
        ),
    )
    return parser.parse_args()


def run_model_smoke_test(
    client: LLMClient,
    configuration: ModelCatalogConfiguration,
    model_id: str,
) -> None:
    profile_config = configuration.get_model_config(model_id)
    if model_id == PUBLIC_PROFILE:
        if profile_config.provider != "groq":
            raise RuntimeError("groq_benchmark is not configured for Groq")
        if profile_config.authentication is not AuthenticationMode.API_KEY:
            raise RuntimeError("groq_benchmark must require API-key authentication")
        if profile_config.api_key_env != "GROQ_API_KEY":
            raise RuntimeError("groq_benchmark must use GROQ_API_KEY")
        prompt = f"Reply exactly with {PUBLIC_EXPECTED_RESPONSE}"
        expected_response = PUBLIC_EXPECTED_RESPONSE
    else:
        if profile_config.provider != "ollama":
            raise RuntimeError(
                "Only groq_benchmark may call a non-Ollama provider from this smoke test"
            )
        if profile_config.authentication is not AuthenticationMode.NONE:
            raise RuntimeError(
                f"Local Ollama model requires authentication: {model_id}"
            )
        prompt = f"Reply exactly with {LOCAL_EXPECTED_RESPONSE}"
        expected_response = LOCAL_EXPECTED_RESPONSE

    request = LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content=prompt),))
    response = client.chat(ModelId(model_id), request)

    if response.text is None or not response.text.strip():
        raise RuntimeError(f"Smoke test response did not contain text: {model_id}")
    actual_response = response.text.strip()
    if actual_response != expected_response:
        raise RuntimeError(
            f"Unexpected smoke test response for {model_id}: {actual_response}"
        )

    print(f"model_id={model_id}")
    print(f"configured_model={profile_config.model}")
    print(f"response={actual_response}")
    print(f"finish_reason={response.finish_reason.value}")


if __name__ == "__main__":
    main()
