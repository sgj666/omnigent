"""Provider-neutral HTTP schemas for editable Agent Bundles."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BundleExecutorConfig(BaseModel):
    """Known executor settings while retaining provider extensions."""

    model_config = ConfigDict(extra="allow")

    harness: str | None = None


class BundleExecutor(BaseModel):
    """Provider-neutral executor selection."""

    model_config = ConfigDict(extra="allow")

    type: str | None = None
    model: str | None = None
    context_window: int | None = None
    config: BundleExecutorConfig | None = None


class BundleTools(BaseModel):
    """Known tool settings while retaining AgentSpec extensions."""

    model_config = ConfigDict(extra="allow")

    agents: list[str] | None = None
    builtins: Any | None = None
    timeout: Any | None = None
    retry: Any | None = None


class BundleConfig(BaseModel):
    """Structured AgentSpec fields; unknown YAML keys round-trip as extras."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    spec_version: int | None = None
    name: str | None = None
    description: str | None = None
    executor: BundleExecutor | None = None
    prompt: Any | None = None
    instructions: Any | None = None
    tools: BundleTools | None = None
    skills: Any | None = None
    mcp: Any | None = None
    mcp_servers: Any | None = None
    os_env: Any | None = None
    environment: Any | None = None
    guardrails: Any | None = None
    policies: Any | None = None
    spawn: Any | None = None
    async_config: Any | None = Field(default=None, alias="async")
    timers: Any | None = None
    params: Any | None = None


class BundleCardResponse(BaseModel):
    """Agent Bundle list item."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    version: int
    digest: str
    readonly: bool


class BundleAgentResponse(BaseModel):
    """Coordinator or worker config with lossless Advanced YAML."""

    name: str
    config: BundleConfig
    advanced_yaml: str


class BundleDetailResponse(BaseModel):
    """Complete editable representation of one Agent Bundle."""

    card: BundleCardResponse
    coordinator: BundleAgentResponse
    workers: list[BundleAgentResponse]


class BundleListResponse(BaseModel):
    """Cursor page of Agent Bundles."""

    object: str = "list"
    data: list[BundleCardResponse]
    first_id: str | None = None
    last_id: str | None = None


class BundleCreateRequest(BaseModel):
    """Create a bundle from structured coordinator config."""

    name: str
    description: str | None = None
    config: BundleConfig


class BundleUpdateRequest(BaseModel):
    """Optimistic coordinator edit."""

    expected_version: int = Field(ge=1)
    coordinator_changes: BundleConfig | None = None
    advanced_yaml: str | None = None
    name: str | None = None
    description: str | None = None


class BundleValidateRequest(BaseModel):
    """Base64-encoded tar bundle to validate without persisting."""

    bundle_base64: str


class BundleCloneRequest(BaseModel):
    """Clone a bundle, including read-only built-ins."""

    name: str
    description: str | None = None


class BundleWorkerCreateRequest(BaseModel):
    """Create one worker in the official AgentSpec worker tree."""

    expected_version: int = Field(ge=1)
    name: str
    config: BundleConfig


class BundleWorkerUpdateRequest(BaseModel):
    """Optimistic structured or Advanced YAML worker edit."""

    expected_version: int = Field(ge=1)
    changes: BundleConfig | None = None
    advanced_yaml: str | None = None


class BundleWorkerDeleteRequest(BaseModel):
    """Optimistic worker deletion."""

    expected_version: int = Field(ge=1)


class BundleWorkerOrderRequest(BaseModel):
    """Replace worker display/execution order with the exact existing set."""

    expected_version: int = Field(ge=1)
    names: list[str]


class BundleValidationIssueResponse(BaseModel):
    """One sanitized validation issue."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    message: str
    path: str | None = None
    line: int | None = None
    column: int | None = None


class BundleValidationResponse(BaseModel):
    """Non-mutating validation result."""

    valid: bool
    issues: list[BundleValidationIssueResponse]


class BundleOptionsResponse(BaseModel):
    """Available provider capabilities without invented defaults."""

    model_config = ConfigDict(extra="allow")

    harnesses: list[dict[str, Any]]
    models: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    mcp: list[dict[str, Any]] = Field(default_factory=list)
    environment: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [name for name in globals() if name.startswith("Bundle")]
