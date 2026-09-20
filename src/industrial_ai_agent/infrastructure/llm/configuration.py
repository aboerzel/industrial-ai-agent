"""Validated infrastructure loader for the pure model catalog."""

import tomllib
from collections.abc import Mapping
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

from industrial_ai_agent.agent.llm import ModelId
from industrial_ai_agent.agent.model_egress import ExecutionZone
from industrial_ai_agent.agent.model_selection import (
    CostClass,
    ModelCapability,
    ModelDefinition,
    QualityClass,
)
from industrial_ai_agent.domain.security import DataClassification


class AuthenticationMode(StrEnum):
    NONE = "none"
    API_KEY = "api_key"


class ModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    provider_model: str = Field(min_length=1)
    base_url: AnyHttpUrl
    temperature: float = Field(ge=0, le=2)
    authentication: AuthenticationMode
    execution_zone: ExecutionZone
    max_data_classification: DataClassification
    capabilities: frozenset[ModelCapability] = Field(min_length=1)
    quality_class: QualityClass
    cost_class: CostClass
    incompatible_capability_combinations: tuple[frozenset[ModelCapability], ...] = ()
    supports_reasoning_effort: bool = False
    max_output_tokens: int | None = Field(default=None, ge=1, le=4096)
    api_cost_usd: Decimal | None = Field(default=None, ge=0)
    api_key_env: str | None = Field(default=None, min_length=1)
    provider_model_env: str | None = Field(default=None, min_length=1)
    base_url_env: str | None = Field(default=None, min_length=1)

    @field_validator("max_data_classification", mode="before")
    @classmethod
    def parse_max_data_classification(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return DataClassification[value]
            except KeyError as error:
                raise ValueError("Invalid maximum data classification") from error
        return value

    @model_validator(mode="after")
    def validate_authentication(self) -> Self:
        if self.authentication is AuthenticationMode.API_KEY and not self.api_key_env:
            raise ValueError("api_key_env is required when authentication is 'api_key'")
        if self.authentication is AuthenticationMode.NONE and self.api_key_env:
            raise ValueError(
                "api_key_env must not be set when authentication is 'none'"
            )
        for combination in self.incompatible_capability_combinations:
            if len(combination) < 2:
                raise ValueError(
                    "Incompatible capability combinations require at least two capabilities"
                )
            if not combination <= self.capabilities:
                raise ValueError(
                    "Incompatible capability combinations must be supported individually"
                )
        return self

    def definition(self) -> ModelDefinition:
        return ModelDefinition(
            model_id=ModelId(self.id),
            display_name=self.display_name,
            provider=self.provider,
            provider_model=self.provider_model,
            execution_zone=self.execution_zone,
            max_data_classification=self.max_data_classification,
            capabilities=self.capabilities,
            quality_class=self.quality_class,
            cost_class=self.cost_class,
            incompatible_capability_combinations=frozenset(
                self.incompatible_capability_combinations
            ),
        )

    @property
    def model(self) -> str:
        """Compatibility name for provider adapter callers during the migration."""
        return self.provider_model

    @property
    def model_env(self) -> str | None:
        return self.provider_model_env

    @property
    def supports_structured_output(self) -> bool:
        return ModelCapability.STRUCTURED_OUTPUT in self.capabilities


class ModelCatalogConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    models: tuple[ModelConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        model_ids = [model.id for model in self.models]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("Model IDs must be unique")
        return self

    def get_model_config(self, model_id: str) -> ModelConfig:
        for model in self.models:
            if model.id == model_id:
                return model
        raise ValueError(f"Unknown model ID: {model_id}")

    def get_profile(self, model_id: str) -> ModelConfig:
        """Compatibility accessor; the key is always a stable model ID."""
        return self.get_model_config(model_id)

    def get_model(self, model_id: str) -> ModelDefinition:
        return self.get_model_config(model_id).definition()

    def list_models(self) -> tuple[ModelDefinition, ...]:
        return tuple(model.definition() for model in self.models)

    def get_execution_zone(self, model_id: str) -> ExecutionZone:
        return self.get_model_config(model_id).execution_zone

    def get_max_data_classification(self, model_id: str) -> DataClassification:
        return self.get_model_config(model_id).max_data_classification

    def is_model_available(
        self, model_id: str, *, environment: Mapping[str, str]
    ) -> bool:
        model = self.get_model_config(model_id)
        return model.authentication is AuthenticationMode.NONE or bool(
            model.api_key_env and environment.get(model.api_key_env, "").strip()
        )


def load_model_catalog(path: Path) -> ModelCatalogConfiguration:
    with path.open("rb") as config_file:
        raw_configuration = tomllib.load(config_file)
    return ModelCatalogConfiguration.model_validate(raw_configuration)


# Import compatibility for scripts while their call sites move to catalog terminology.
LLMConfiguration = ModelCatalogConfiguration
ModelProfileConfig = ModelConfig
load_llm_configuration = load_model_catalog
