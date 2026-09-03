from pathlib import Path

from dotenv import load_dotenv

from industrial_ai_agent.agent.llm import (
    LLMMessage,
    LLMRequest,
    MessageRole,
    ModelProfile,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    load_llm_configuration,
)
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TROUBLESHOOTING_PROFILE = ModelProfile("troubleshooting")


def main() -> None:
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
        response = client.chat(TROUBLESHOOTING_PROFILE, request)

    if response.text is None:
        raise RuntimeError("Smoke test response did not contain text")
    print(response.text)
    print(f"finish_reason={response.finish_reason.value}")


if __name__ == "__main__":
    main()
