import os
import tomllib
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from industrial_ai_agent.agent.llm import ModelProfile
from industrial_ai_agent.agent.model_egress import ExecutionZone
from industrial_ai_agent.agent.model_routing import (
    CostClass,
    LLMCapability,
    ModelProfileMetadata,
    QualityClass,
)
from industrial_ai_agent.domain.security import DataClassification


class AuthenticationMode(StrEnum):
    NONE = "none"
    API_KEY = "api_key"


LOCAL_ONLY_MODE_ENV = "LOCAL_ONLY_MODE"


class ModelProfileConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: AnyHttpUrl
    temperature: float = Field(ge=0, le=2)
    authentication: AuthenticationMode
    execution_zone: ExecutionZone
    max_data_classification: DataClassification
    capabilities: frozenset[LLMCapability] = Field(min_length=1)
    quality_class: QualityClass
    cost_class: CostClass
    supports_structured_output: bool = False
    supports_reasoning_effort: bool = False
    api_cost_usd: Decimal | None = Field(default=None, ge=0)
    api_key_env: str | None = Field(default=None, min_length=1)

    @field_validator("max_data_classification", mode="before")
    @classmethod
    def parse_max_data_classification(cls, value: object) -> DataClassification:
        if isinstance(value, DataClassification):
            return value
        if isinstance(value, str):
            try:
                return DataClassification[value]
            except KeyError as error:
                raise ValueError("Unknown maximum data classification") from error
        raise ValueError("Unknown maximum data classification")

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

    def get_execution_zone(self, profile_name: str) -> ExecutionZone:
        return self.get_profile(profile_name).execution_zone

    def get_max_data_classification(self, profile_name: str) -> DataClassification:
        return self.get_profile(profile_name).max_data_classification

    def get_routing_profiles(
        self, *, local_only: bool = False
    ) -> tuple[ModelProfileMetadata, ...]:
        return tuple(
            ModelProfileMetadata(
                profile=ModelProfile(profile_name),
                capabilities=profile.capabilities,
                quality_class=profile.quality_class,
                cost_class=profile.cost_class,
                execution_zone=profile.execution_zone,
                max_data_classification=profile.max_data_classification,
            )
            for profile_name, profile in sorted(self.profiles.items())
            if not local_only or profile.execution_zone is ExecutionZone.LOCAL
        )


def load_llm_configuration(path: Path) -> LLMConfiguration:
    with path.open("rb") as config_file:
        raw_configuration = tomllib.load(config_file)
    return LLMConfiguration.model_validate(raw_configuration)


def local_only_mode_enabled() -> bool:
    value = os.getenv(LOCAL_ONLY_MODE_ENV, "false").strip().lower()
    if value in {"0", "false"}:
        return False
    if value in {"1", "true"}:
        return True
    raise ValueError(f"{LOCAL_ONLY_MODE_ENV} must be either 'true' or 'false'")
