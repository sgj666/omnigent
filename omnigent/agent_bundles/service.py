"""Application service for editable Agent Bundles."""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ruamel.yaml import YAML

from omnigent.agent_bundles.document import BundleDocument
from omnigent.agent_bundles.workers import BundleAgentView, BundleWorkers
from omnigent.db.utils import builtin_agent_id, generate_agent_id
from omnigent.entities import Agent
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.bundles import bundle_location, validate_agent_bundle
from omnigent.spec import ExtractionError
from omnigent.stores.agent_store import AgentStore
from omnigent.stores.artifact_store import ArtifactStore


@dataclass(frozen=True)
class BundleIssue:
    """A content-safe Agent Bundle validation issue."""

    code: str
    message: str
    path: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class BundleValidationResult:
    """Result of validating bundle bytes without persisting them."""

    valid: bool
    issues: tuple[BundleIssue, ...] = ()


class BundleValidationFailure(OmnigentError):
    """Raised when proposed bundle contents are invalid."""

    def __init__(self, issues: Sequence[BundleIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__(
            "agent bundle validation failed",
            code=ErrorCode.INVALID_INPUT,
        )


@dataclass(frozen=True)
class BundleCard:
    """List representation of a persisted Agent Bundle."""

    id: str
    name: str
    description: str | None
    version: int
    digest: str
    readonly: bool


@dataclass(frozen=True)
class BundlePage:
    """A cursor page of Agent Bundle cards."""

    data: tuple[BundleCard, ...]
    first_id: str | None
    last_id: str | None


@dataclass(frozen=True)
class BundleDetail:
    """Editable coordinator and worker views for one Agent Bundle."""

    card: BundleCard
    coordinator: BundleAgentView
    workers: tuple[BundleAgentView, ...]


class AgentBundleService:
    """Coordinate lossless edits with agent and artifact persistence."""

    def __init__(self, agent_store: AgentStore, artifact_store: ArtifactStore) -> None:
        self._agents = agent_store
        self._artifacts = artifact_store

    @staticmethod
    def location(agent_id: str, bundle_bytes: bytes) -> str:
        """Return the content-addressed artifact key for *bundle_bytes*."""
        return bundle_location(agent_id, bundle_bytes)

    def list(
        self,
        *,
        limit: int = 20,
        after: str | None = None,
        before: str | None = None,
        order: str = "desc",
    ) -> BundlePage:
        page = self._agents.list(limit=limit, after=after, before=before, order=order)
        return BundlePage(
            data=tuple(self._card(agent) for agent in page.data),
            first_id=page.first_id,
            last_id=page.last_id,
        )

    def get(self, agent_id: str) -> BundleDetail:
        agent = self._require_agent(agent_id)
        return self._detail(agent, self._load_document(agent))

    def export(self, agent_id: str) -> bytes:
        agent = self._require_agent(agent_id)
        return self._artifacts.get(agent.bundle_location)

    def validate(self, bundle_bytes: bytes) -> BundleValidationResult:
        try:
            validate_agent_bundle(bundle_bytes)
        except Exception:  # noqa: BLE001 - untrusted validation errors are sanitized
            return BundleValidationResult(
                valid=False,
                issues=(
                    BundleIssue(
                        code="invalid_bundle",
                        message="bundle does not satisfy AgentSpec",
                    ),
                ),
            )
        return BundleValidationResult(valid=True)

    def import_bundle(
        self,
        bundle_bytes: bytes,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> BundleCard:
        document = self._validated_document(bundle_bytes)
        coordinator = BundleWorkers.coordinator(document)
        persisted_name = name if name is not None else coordinator.name
        if not persisted_name:
            raise BundleValidationFailure(
                (BundleIssue("invalid_bundle", "bundle does not satisfy AgentSpec"),)
            )
        import_changes: dict[str, object] = {}
        if name is not None and coordinator.name != name:
            import_changes["name"] = name
        if description is not None:
            import_changes["description"] = description
        if import_changes:
            BundleWorkers.update_coordinator(document, import_changes)
            coordinator = BundleWorkers.coordinator(document)
        rendered = document.to_bytes()
        self._require_valid(rendered)
        agent_id = generate_agent_id()
        location = self.location(agent_id, rendered)
        self._artifacts.put(location, rendered)
        persisted_description = self._config_description(coordinator.config, description)
        agent = self._agents.create(
            agent_id,
            persisted_name,
            location,
            persisted_description,
        )
        return self._card(agent)

    def create(
        self,
        *,
        name: str,
        config: Mapping[str, object],
        description: str | None = None,
    ) -> BundleCard:
        rendered_config = dict(config)
        rendered_config["name"] = name
        bundle = BundleDocument(
            {"config.yaml": self._render_yaml(rendered_config).encode("utf-8")}
        ).to_bytes()
        return self.import_bundle(bundle, name=name, description=description)

    def clone(
        self,
        agent_id: str,
        *,
        name: str,
        description: str | None = None,
    ) -> BundleCard:
        source = self._require_agent(agent_id)
        document = self._load_document(source)
        clone_changes: dict[str, object] = {"name": name}
        if description is not None:
            clone_changes["description"] = description
        BundleWorkers.update_coordinator(document, clone_changes)
        rendered = document.to_bytes()
        self._require_valid(rendered)
        clone_id = generate_agent_id()
        location = self.location(clone_id, rendered)
        self._artifacts.put(location, rendered)
        clone = self._agents.create(
            clone_id,
            name,
            location,
            source.description if description is None else description,
        )
        return self._card(clone)

    def update(
        self,
        agent_id: str,
        *,
        expected_version: int,
        coordinator_changes: Mapping[str, object] | None = None,
        advanced_yaml: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> BundleDetail:
        agent, document = self._editable_document(agent_id)
        if coordinator_changes:
            BundleWorkers.update_coordinator(document, coordinator_changes)
        metadata_changes: dict[str, object] = {}
        if name is not None:
            metadata_changes["name"] = name
        if description is not None:
            metadata_changes["description"] = description
        if metadata_changes:
            BundleWorkers.update_coordinator(document, metadata_changes)
        try:
            if advanced_yaml is not None:
                BundleWorkers.replace_advanced_yaml(document, None, advanced_yaml)
        except Exception as exc:
            if advanced_yaml is not None:
                raise self._invalid_yaml(exc, "config.yaml") from None
            raise

        coordinator = BundleWorkers.coordinator(document)
        persisted_name = name if name is not None else coordinator.name or agent.name
        persisted_description = (
            description
            if description is not None
            else self._config_description(coordinator.config, agent.description)
        )
        return self._persist_update(
            agent,
            document,
            expected_version=expected_version,
            name=persisted_name,
            description=persisted_description,
        )

    def create_worker(
        self,
        agent_id: str,
        worker_name: str,
        config: Mapping[str, object],
        *,
        expected_version: int,
    ) -> BundleDetail:
        agent, document = self._editable_document(agent_id)
        BundleWorkers.create(document, worker_name, config)
        return self._persist_existing_metadata(agent, document, expected_version)

    def update_worker(
        self,
        agent_id: str,
        worker_name: str,
        changes: Mapping[str, object],
        *,
        expected_version: int,
        advanced_yaml: str | None = None,
    ) -> BundleDetail:
        agent, document = self._editable_document(agent_id)
        if changes:
            BundleWorkers.update(document, worker_name, changes)
        try:
            if advanced_yaml is not None:
                BundleWorkers.replace_advanced_yaml(document, worker_name, advanced_yaml)
        except Exception as exc:
            if advanced_yaml is not None:
                raise self._invalid_yaml(
                    exc,
                    f"agents/{worker_name}/config.yaml",
                ) from None
            raise
        return self._persist_existing_metadata(agent, document, expected_version)

    def delete_worker(
        self,
        agent_id: str,
        worker_name: str,
        *,
        expected_version: int,
    ) -> BundleDetail:
        agent, document = self._editable_document(agent_id)
        BundleWorkers.delete(document, worker_name)
        return self._persist_existing_metadata(agent, document, expected_version)

    def reorder_workers(
        self,
        agent_id: str,
        names: Sequence[str],
        *,
        expected_version: int,
    ) -> BundleDetail:
        agent, document = self._editable_document(agent_id)
        BundleWorkers.reorder(document, names)
        return self._persist_existing_metadata(agent, document, expected_version)

    def delete(self, agent_id: str) -> None:
        agent = self._require_agent(agent_id)
        self._require_editable(agent)
        if not self._agents.delete(agent_id):
            raise KeyError(f"agent bundle {agent_id!r} not found")
        self._artifacts.delete(agent.bundle_location)

    def _persist_existing_metadata(
        self,
        agent: Agent,
        document: BundleDocument,
        expected_version: int,
    ) -> BundleDetail:
        return self._persist_update(
            agent,
            document,
            expected_version=expected_version,
            name=agent.name,
            description=agent.description,
        )

    def _persist_update(
        self,
        agent: Agent,
        document: BundleDocument,
        *,
        expected_version: int,
        name: str,
        description: str | None,
    ) -> BundleDetail:
        rendered = document.to_bytes()
        self._require_valid(rendered)
        location = self.location(agent.id, rendered)
        self._artifacts.put(location, rendered)
        updated = self._agents.update_template(
            agent.id,
            location,
            name,
            description,
            expected_version,
        )
        if updated is None:
            raise KeyError(f"agent bundle {agent.id!r} not found")
        return self._detail(updated, document)

    def _validated_document(self, bundle_bytes: bytes) -> BundleDocument:
        self._require_valid(bundle_bytes)
        try:
            document = BundleDocument.from_bytes(bundle_bytes)
        except (ExtractionError, TypeError, ValueError):
            raise BundleValidationFailure(
                (BundleIssue("invalid_bundle", "bundle does not satisfy AgentSpec"),)
            ) from None
        if not document.exists("config.yaml"):
            raise BundleValidationFailure(
                (BundleIssue("invalid_bundle", "bundle does not satisfy AgentSpec"),)
            )
        return document

    def _require_valid(self, bundle_bytes: bytes) -> None:
        result = self.validate(bundle_bytes)
        if not result.valid:
            raise BundleValidationFailure(result.issues)

    def _editable_document(self, agent_id: str) -> tuple[Agent, BundleDocument]:
        agent = self._require_agent(agent_id)
        self._require_editable(agent)
        return agent, self._load_document(agent)

    def _require_agent(self, agent_id: str) -> Agent:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"agent bundle {agent_id!r} not found")
        return agent

    @staticmethod
    def _require_editable(agent: Agent) -> None:
        if agent.id == builtin_agent_id("polly"):
            raise PermissionError("built-in Polly is read-only")

    def _load_document(self, agent: Agent) -> BundleDocument:
        return BundleDocument.from_bytes(self._artifacts.get(agent.bundle_location))

    def _detail(self, agent: Agent, document: BundleDocument) -> BundleDetail:
        return BundleDetail(
            card=self._card(agent),
            coordinator=BundleWorkers.coordinator(document),
            workers=tuple(BundleWorkers.list(document)),
        )

    @staticmethod
    def _card(agent: Agent) -> BundleCard:
        digest = agent.bundle_location.rsplit("/", 1)[-1]
        return BundleCard(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            version=agent.version,
            digest=digest,
            readonly=agent.id == builtin_agent_id("polly"),
        )

    @staticmethod
    def _config_description(config: Mapping[str, Any], fallback: str | None) -> str | None:
        if "description" not in config:
            return fallback
        value = config["description"]
        return value if isinstance(value, str) else None

    @staticmethod
    def _invalid_yaml(exc: Exception, path: str) -> BundleValidationFailure:
        mark = getattr(exc, "problem_mark", None)
        line = getattr(mark, "line", None)
        column = getattr(mark, "column", None)
        return BundleValidationFailure(
            (
                BundleIssue(
                    code="invalid_yaml",
                    message="invalid YAML",
                    path=path,
                    line=line + 1 if isinstance(line, int) else None,
                    column=column + 1 if isinstance(column, int) else None,
                ),
            )
        )

    @staticmethod
    def _render_yaml(value: Mapping[str, object]) -> str:
        stream = io.StringIO()
        yaml = YAML(typ="rt")
        yaml.dump(dict(value), stream)
        return stream.getvalue()


__all__ = [
    "AgentBundleService",
    "BundleCard",
    "BundleDetail",
    "BundleIssue",
    "BundlePage",
    "BundleValidationFailure",
    "BundleValidationResult",
]
