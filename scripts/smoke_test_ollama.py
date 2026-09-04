import argparse
from pathlib import Path

from industrial_ai_agent.agent.llm import (
    LLMClient,
    LLMMessage,
    LLMRequest,
    MessageRole,
    ModelProfile,
)
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    EgressCheckedLLMClient,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    AuthenticationMode,
    LLMConfiguration,
    load_llm_configuration,
)
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.local_environment import (
    load_local_environment,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILES = ("local_fast", "local_quality")
PUBLIC_PROFILE = "public_fast"
LOCAL_EXPECTED_RESPONSE = "Industrial AI Agent ready"
PUBLIC_EXPECTED_RESPONSE = "PUBLIC_LLM_OK"


def main() -> None:
    args = parse_args()
    profile_names = tuple(args.profiles or DEFAULT_PROFILES)
    load_local_environment(PROJECT_ROOT / ".env")
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )

    with OpenAICompatibleLLMClient(configuration) as adapter:
        client = EgressCheckedLLMClient(
            adapter,
            configuration,
            DataClassification.PUBLIC,
        )
        for profile_name in profile_names:
            run_profile_smoke_test(client, configuration, profile_name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explicitly call one or more configured model profiles."
    )
    parser.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        metavar="PROFILE",
        help=(
            "Semantic model profile to call. Repeat for multiple profiles. "
            "Defaults to local_fast and local_quality."
        ),
    )
    return parser.parse_args()


def run_profile_smoke_test(
    client: LLMClient,
    configuration: LLMConfiguration,
    profile_name: str,
) -> None:
    profile_config = configuration.get_profile(profile_name)
    if profile_name == PUBLIC_PROFILE:
        if profile_config.provider != "groq":
            raise RuntimeError("public_fast is not configured for Groq")
        if profile_config.authentication is not AuthenticationMode.API_KEY:
            raise RuntimeError("public_fast must require API-key authentication")
        if profile_config.api_key_env != "GROQ_API_KEY":
            raise RuntimeError("public_fast must use GROQ_API_KEY")
        prompt = f"Reply exactly with {PUBLIC_EXPECTED_RESPONSE}"
        expected_response = PUBLIC_EXPECTED_RESPONSE
    else:
        if profile_config.provider != "ollama":
            raise RuntimeError(
                "Only public_fast may call a non-Ollama provider from this smoke test"
            )
        if profile_config.authentication is not AuthenticationMode.NONE:
            raise RuntimeError(
                f"Local Ollama profile requires authentication: {profile_name}"
            )
        prompt = f"Reply exactly with {LOCAL_EXPECTED_RESPONSE}"
        expected_response = LOCAL_EXPECTED_RESPONSE

    request = LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content=prompt),))
    response = client.chat(ModelProfile(profile_name), request)

    if response.text is None or not response.text.strip():
        raise RuntimeError(f"Smoke test response did not contain text: {profile_name}")
    actual_response = response.text.strip()
    if actual_response != expected_response:
        raise RuntimeError(
            f"Unexpected smoke test response for {profile_name}: {actual_response}"
        )

    print(f"profile={profile_name}")
    print(f"configured_model={profile_config.model}")
    print(f"response={actual_response}")
    print(f"finish_reason={response.finish_reason.value}")


if __name__ == "__main__":
    main()
