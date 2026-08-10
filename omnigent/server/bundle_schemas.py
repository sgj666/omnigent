"""Provider-neutral HTTP schemas for editable Agent Bundles."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BundleExecutorConfig(BaseModel):
    """Known executor settings while retaining provider extensions."""

    model_config = ConfigDict(extra="allow")

    harness: str | None = None
    model: str | None = None


class BundleExecutor(BaseModel):
    """Provider-neutral executor selection."""

    model_config = ConfigDict(extra="allow")

    type: str | None = None
    model: str | None = None
    context_window: int | None = None
    auth: Any | None = None
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
    llm: Any | None = None
    interaction: Any | None = None
    executor: BundleExecutor | None = None
    prompt: str | None = None
    instructions: str | None = None
    tools: BundleTools | None = None
    remote_skills: list[str] | None = None
    skills: Any | None = None
    mcp: Any | None = None
    mcp_servers: Any | None = None
    os_env: Any | None = None
    environment: Any | None = None
    terminals: Any | None = None
    compaction: Any | None = None
    guardrails: Any | None = None
    policies: Any | None = None
    spawn: Any | None = None
    async_config: Any | None = Field(default=None, alias="async")
    timers: Any | None = None
    agent_session_sharing: Any | None = None
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
    harness: str | None
    worker_count: int = Field(ge=0)
    skill_count: int = Field(ge=0)
    mcp_count: int = Field(ge=0)
    validation_status: Literal["valid", "invalid", "unknown"]
    updated_at: int
    builtin: bool
    editable: bool


class BundleAgentResponse(BaseModel):
    """Coordinator or worker config with lossless Advanced YAML."""

    name: str
    path: str
    content: str
    data: BundleConfig
    config: BundleConfig
    advanced_yaml: str


class BundleFileResponse(BaseModel):
    """One safe regular-file entry in the complete bundle tree."""

    model_config = ConfigDict(from_attributes=True)

    path: str
    content: str | None
    encoding: Literal["utf-8", "binary"]
    media_type: str | None
    size: int = Field(ge=0)
    data: Any | None = None
    inline: bool


class BundleDetailResponse(BaseModel):
    """Complete editable representation of one Agent Bundle."""

    card: BundleCardResponse
    version: int
    digest: str
    files: list[BundleFileResponse]
    coordinator: BundleAgentResponse
    workers: list[BundleAgentResponse]
    diagnostics: list[BundleDiagnosticResponse]
    schema_version: str


class BundleListResponse(BaseModel):
    """Cursor page of Agent Bundles."""

    object: str = "list"
    data: list[BundleCardResponse]
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False


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
    patches: list[BundlePatchRequest] = Field(default_factory=list)
    worker_operations: list[BundleWorkerOperationRequest] = Field(default_factory=list)


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
    confirmed_references: list[str] = Field(default_factory=list)


class BundleWorkerOrderRequest(BaseModel):
    """Replace worker display/execution order with the exact existing set."""

    expected_version: int = Field(ge=1)
    names: list[str]


class BundleDiagnosticResponse(BaseModel):
    """Safe validation diagnostic shared by detail and validation responses."""

    model_config = ConfigDict(from_attributes=True)

    severity: Literal["error", "warning", "info"] = "error"
    code: str
    file: str | None = None
    path: str | None = None
    line: int | None = None
    column: int | None = None
    agent: str | None = None
    worker: str | None = None
    message: str
    summary_key: str | None = None


class BundleValidationResponse(BaseModel):
    """Non-mutating validation result."""

    valid: bool
    diagnostics: list[BundleDiagnosticResponse]


class BundlePatchRequest(BaseModel):
    """One lossless YAML or text-file patch."""

    file: str = Field(min_length=1)
    op: Literal["add", "replace", "remove", "replace_file", "delete_file"]
    path: str = ""
    value: Any = None


class BundleWorkerOperationRequest(BaseModel):
    """One atomic worker-tree operation."""

    op: Literal["add", "copy", "rename", "delete"]
    name: str | None = None
    source: str | None = None
    target: str | None = None
    confirmed_references: list[str] = Field(default_factory=list)


class BundleFormFieldResponse(BaseModel):
    """UI metadata for one official Agent YAML domain."""

    path: str
    type: Literal["string", "integer", "number", "boolean", "array", "object"]
    group: str
    required: bool = False
    default: Any | None = None
    enum: list[Any] | None = None
    secret: bool = False
    translation_key: str
    help_translation_key: str | None = None
    editor: str = "generic-tree"


class BundleFormSchemaResponse(BaseModel):
    """Versioned Pydantic JSON Schema plus editor metadata."""

    schema_version: str
    json_schema: dict[str, Any] = Field(alias="schema")
    fields: list[BundleFormFieldResponse]


class BundleOptionsResponse(BaseModel):
    """Available provider capabilities without invented defaults."""

    model_config = ConfigDict(extra="allow")

    harnesses: list[dict[str, Any]]
    models: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    mcp: list[dict[str, Any]] = Field(default_factory=list)
    environment: list[dict[str, Any]] = Field(default_factory=list)


_FIELD_EDITORS = {
    "prompt": "textarea",
    "instructions": "textarea",
    "tools": "generic-tree",
    "skills": "generic-tree",
    "mcp": "mcp-list",
    "mcp_servers": "mcp-list",
    "os_env": "sandbox",
    "environment": "generic-tree",
    "terminals": "terminal-map",
    "guardrails": "generic-tree",
    "policies": "policy-map",
    "params": "params",
    "async": "tri-state",
    "timers": "tri-state",
    "spawn": "tri-state",
}


def _json_schema_type(schema: dict[str, Any]) -> str:
    value = schema.get("type")
    if value in {"string", "integer", "number", "boolean", "array", "object"}:
        return str(value)
    for candidate in schema.get("anyOf", []):
        candidate_type = candidate.get("type")
        if candidate_type != "null":
            return _json_schema_type(candidate)
    return "object"


def build_bundle_form_schema() -> BundleFormSchemaResponse:
    """Return the versioned editor schema derived from the wire Pydantic model."""
    schema = BundleConfig.model_json_schema(by_alias=True)
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: list[BundleFormFieldResponse] = []
    for name, field_schema in properties.items():
        editor = _FIELD_EDITORS.get(name, "text")
        field_type = _json_schema_type(field_schema)
        if field_type in {"object", "array"} and name not in _FIELD_EDITORS:
            editor = "generic-tree"
        fields.append(
            BundleFormFieldResponse(
                path=f"/{name}",
                type=field_type,
                group=(
                    "runtime"
                    if name in {"async", "timers", "spawn", "agent_session_sharing"}
                    else name
                ),
                required=name in required,
                default=field_schema.get("default"),
                enum=field_schema.get("enum"),
                translation_key=f"multiAgent.fields.{name}",
                editor=editor,
            )
        )
    fields.extend(
        [
            BundleFormFieldResponse(
                path="/executor/type",
                type="string",
                group="executor",
                translation_key="multiAgent.fields.executorType",
                editor="text",
            ),
            BundleFormFieldResponse(
                path="/executor/model",
                type="string",
                group="executor",
                translation_key="multiAgent.fields.model",
                editor="text",
            ),
            BundleFormFieldResponse(
                path="/executor/context_window",
                type="integer",
                group="executor",
                translation_key="multiAgent.fields.contextWindow",
                editor="text",
            ),
            BundleFormFieldResponse(
                path="/executor/auth",
                type="object",
                group="executor",
                secret=True,
                translation_key="multiAgent.fields.auth",
                editor="generic-tree",
            ),
            BundleFormFieldResponse(
                path="/executor/config",
                type="object",
                group="executor",
                translation_key="multiAgent.fields.executorConfig",
                editor="generic-tree",
            ),
            BundleFormFieldResponse(
                path="/executor/config/harness",
                type="string",
                group="executor",
                translation_key="multiAgent.fields.harness",
                editor="select",
            ),
            BundleFormFieldResponse(
                path="/*",
                type="object",
                group="advanced",
                translation_key="multiAgent.fields.extensions",
                editor="generic-tree",
            ),
        ]
    )
    return BundleFormSchemaResponse(schema_version="1", schema=schema, fields=fields)


__all__ = [name for name in globals() if name.startswith("Bundle")]
