import argparse
from pathlib import Path

from dotenv import load_dotenv

from industrial_ai_agent.agent.llm import (
    LLMMessage,
    LLMRequest,
    MessageRole,
    ModelProfile,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    AuthenticationMode,
    LLMConfiguration,
    load_llm_configuration,
)
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILES = ("local_fast", "local_quality")


def main() -> None:
    args = parse_args()
    profile_names = tuple(args.profiles or DEFAULT_PROFILES)
    load_dotenv(PROJECT_ROOT / ".env")
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    request = LLMRequest(
        messages=(
            LLMMessage(
                role=MessageRole.USER,
                content="Reply with exactly: Industrial AI Agent ready",
            ),
        )
    )

    with OpenAICompatibleLLMClient(configuration) as client:
        for profile_name in profile_names:
            run_profile_smoke_test(client, configuration, profile_name, request)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Call one or more configured local Ollama model profiles."
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
    client: OpenAICompatibleLLMClient,
    configuration: LLMConfiguration,
    profile_name: str,
    request: LLMRequest,
) -> None:
    profile_config = configuration.get_profile(profile_name)
    if profile_config.provider != "ollama":
        raise RuntimeError(
            f"Smoke test profile is not configured for Ollama: {profile_name}"
        )
    if profile_config.authentication is not AuthenticationMode.NONE:
        raise RuntimeError(
            f"Local Ollama smoke test profile requires authentication: {profile_name}"
        )

    response = client.chat(ModelProfile(profile_name), request)

    if response.text is None or not response.text.strip():
        raise RuntimeError(f"Smoke test response did not contain text: {profile_name}")
    print(f"profile={profile_name}")
    print(f"configured_model={profile_config.model}")
    print(f"response={response.text.strip()}")
    print(f"finish_reason={response.finish_reason.value}")


if __name__ == "__main__":
    main()
