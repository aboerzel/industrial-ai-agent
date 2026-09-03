import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class AuthenticationMode(StrEnum):
    NONE = "none"
    API_KEY = "api_key"


class ModelProfileConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: AnyHttpUrl
    temperature: float = Field(ge=0, le=2)
    authentication: AuthenticationMode
    api_key_env: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_authentication(self) -> Self:
        if self.authentication is AuthenticationMode.API_KEY and not self.api_key_env:
            raise ValueError("api_key_env is required when authentication is 'api_key'")
        if self.authentication is AuthenticationMode.NONE and self.api_key_env:
            raise ValueError(
                "api_key_env must not be set when authentication is 'none'"
            )
        return self


class LLMConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    profiles: dict[str, ModelProfileConfig]

    def get_profile(self, profile: str) -> ModelProfileConfig:
        try:
            return self.profiles[profile]
        except KeyError as error:
            raise ValueError(f"Unknown model profile: {profile}") from error


def load_llm_configuration(path: Path) -> LLMConfiguration:
    with path.open("rb") as config_file:
        raw_configuration = tomllib.load(config_file)
    return LLMConfiguration.model_validate(raw_configuration)
