"""Application service for editable Agent Bundles."""

from __future__ import annotations

import copy
import io
import json
import mimetypes
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from ruamel.yaml import YAML

from omnigent.agent_bundles.document import BundleDocument, BundleFileSizeError
from omnigent.agent_bundles.patches import BundlePatch, apply_patches
from omnigent.agent_bundles.workers import BundleAgentView, BundleWorkers
from omnigent.db.utils import builtin_agent_id, generate_agent_id
from omnigent.entities import Agent
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.bundles import bundle_location, validate_agent_bundle
from omnigent.skills import SkillRecord, SkillRepositoryReader
from omnigent.spec import ExtractionError
from omnigent.stores.agent_store import AgentStore
from omnigent.stores.artifact_store import ArtifactStore


@dataclass(frozen=True)
class BundleIssue:
    """A content-safe Agent Bundle validation issue."""

    code: str
    message: str
    file: str | None = None
    path: str | None = None
    line: int | None = None
    column: int | None = None
    agent: str | None = None
    worker: str | None = None


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
    harness: str | None = None
    worker_count: int = 0
    skill_count: int = 0
    mcp_count: int = 0
    validation_status: Literal["valid", "invalid", "unknown"] = "valid"
    updated_at: int = 0
    builtin: bool = False
    editable: bool = True


@dataclass(frozen=True)
class BundlePage:
    """A cursor page of Agent Bundle cards."""

    data: tuple[BundleCard, ...]
    first_id: str | None
    last_id: str | None
    has_more: bool = False


@dataclass(frozen=True)
class BundleDetail:
    """Editable coordinator and worker views for one Agent Bundle."""

    card: BundleCard
    coordinator: BundleAgentView
    workers: tuple[BundleAgentView, ...]
    files: tuple[BundleFile, ...] = ()
    diagnostics: tuple[BundleIssue, ...] = ()
    schema_version: str = "1"


@dataclass(frozen=True)
class BundleFile:
    """Safe file-tree entry returned to the browser editor."""

    path: str
    content: str | None
    encoding: str
    media_type: str | None
    size: int
    data: object | None = None
    inline: bool = True


@dataclass(frozen=True)
class BundleWorkerOperation:
    """One atomic worker directory operation."""

    op: Literal["add", "copy", "rename", "delete"]
    name: str | None = None
    source: str | None = None
    target: str | None = None
    confirmed_references: tuple[str, ...] = ()


_MAX_INLINE_FILE_BYTES = 1024 * 1024
_MAX_INLINE_TOTAL_BYTES = 8 * 1024 * 1024
_REMOTE_SKILL_MARKER = ".omnigent-remote-skill.json"


class AgentBundleService:
    """Coordinate lossless edits with agent and artifact persistence."""

    def __init__(
        self,
        agent_store: AgentStore,
        artifact_store: ArtifactStore,
        *,
        skills_reader: SkillRepositoryReader | None = None,
    ) -> None:
        self._agents = agent_store
        self._artifacts = artifact_store
        self._skills_reader = skills_reader

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
            data=tuple(self._list_card(agent) for agent in page.data),
            first_id=page.first_id,
            last_id=page.last_id,
            has_more=page.has_more,
        )

    def _list_card(self, agent: Agent) -> BundleCard:
        try:
            document = self._load_document(agent)
            self._require_inline_agent_configs(document)
            return self._card(agent, document)
        except (BundleValidationFailure, ExtractionError, KeyError, TypeError, ValueError):
            digest = agent.bundle_location.rsplit("/", 1)[-1]
            builtin = self._is_builtin(agent)
            return BundleCard(
                id=agent.id,
                name=agent.name,
                description=agent.description,
                version=agent.version,
                digest=digest,
                readonly=builtin,
                validation_status="unknown",
                updated_at=(
                    agent.updated_at if agent.updated_at is not None else agent.created_at
                ),
                builtin=builtin,
                editable=not builtin,
            )

    def get(self, agent_id: str) -> BundleDetail:
        agent = self._require_agent(agent_id)
        return self._detail(agent, self._load_document(agent))

    def export(self, agent_id: str) -> bytes:
        agent = self._require_agent(agent_id)
        return self._artifacts.get(agent.bundle_location)

    def validate(self, bundle_bytes: bytes) -> BundleValidationResult:
        try:
            document = BundleDocument.from_bytes(bundle_bytes)
            issue = self._agent_config_limit_issue(document)
            if issue is not None:
                return BundleValidationResult(valid=False, issues=(issue,))
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
            try:
                BundleWorkers.update_coordinator(document, import_changes)
            except BundleFileSizeError as exc:
                raise self._agent_config_too_large(exc.path) from None
            self._require_inline_agent_configs(document)
            coordinator = BundleWorkers.coordinator(document)
        self._sync_remote_skills(document)
        self._require_inline_agent_configs(document)
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
        return self._card(agent, document)

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
        self._require_inline_agent_configs(document)
        clone_changes: dict[str, object] = {"name": name}
        if description is not None:
            clone_changes["description"] = description
        try:
            BundleWorkers.update_coordinator(document, clone_changes)
        except BundleFileSizeError as exc:
            raise self._agent_config_too_large(exc.path) from None
        self._sync_remote_skills(document)
        self._require_inline_agent_configs(document)
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
        return self._card(clone, document)

    def update(
        self,
        agent_id: str,
        *,
        expected_version: int,
        coordinator_changes: Mapping[str, object] | None = None,
        advanced_yaml: str | None = None,
        name: str | None = None,
        description: str | None = None,
        patches: Sequence[BundlePatch] | None = None,
        worker_operations: Sequence[BundleWorkerOperation] | None = None,
    ) -> BundleDetail:
        agent, document = self._editable_document(agent_id)
        if patches:
            try:
                apply_patches(document, patches)
            except BundleFileSizeError as exc:
                raise self._agent_config_too_large(exc.path) from None
            except Exception as exc:
                raise BundleValidationFailure(
                    (BundleIssue("invalid_patch", "patch could not be applied"),)
                ) from exc
        for operation in worker_operations or ():
            self._apply_worker_operation(document, operation)
        try:
            if coordinator_changes:
                BundleWorkers.update_coordinator(document, coordinator_changes)
        except BundleFileSizeError as exc:
            raise self._agent_config_too_large(exc.path) from None
        metadata_changes: dict[str, object] = {}
        if name is not None:
            metadata_changes["name"] = name
        if description is not None:
            metadata_changes["description"] = description
        try:
            if metadata_changes:
                BundleWorkers.update_coordinator(document, metadata_changes)
        except BundleFileSizeError as exc:
            raise self._agent_config_too_large(exc.path) from None
        try:
            if advanced_yaml is not None:
                self._require_agent_config_text("config.yaml", advanced_yaml)
                BundleWorkers.replace_advanced_yaml(document, None, advanced_yaml)
        except BundleValidationFailure:
            raise
        except Exception as exc:
            if advanced_yaml is not None:
                raise self._invalid_yaml(exc, "config.yaml") from None
            raise

        self._require_inline_agent_configs(document)
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
        try:
            BundleWorkers.create(document, worker_name, config)
        except BundleFileSizeError as exc:
            raise self._agent_config_too_large(exc.path) from None
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
        try:
            if changes:
                BundleWorkers.update(document, worker_name, changes)
        except BundleFileSizeError as exc:
            raise self._agent_config_too_large(exc.path) from None
        try:
            if advanced_yaml is not None:
                self._require_agent_config_text(f"agents/{worker_name}/config.yaml", advanced_yaml)
                BundleWorkers.replace_advanced_yaml(document, worker_name, advanced_yaml)
        except BundleValidationFailure:
            raise
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
        confirmed_references: Sequence[str] = (),
    ) -> BundleDetail:
        agent, document = self._editable_document(agent_id)
        try:
            self._delete_worker(document, worker_name, confirmed_references)
        except BundleFileSizeError as exc:
            raise self._agent_config_too_large(exc.path) from None
        return self._persist_existing_metadata(agent, document, expected_version)

    def reorder_workers(
        self,
        agent_id: str,
        names: Sequence[str],
        *,
        expected_version: int,
    ) -> BundleDetail:
        agent, document = self._editable_document(agent_id)
        try:
            BundleWorkers.reorder(document, names)
        except BundleFileSizeError as exc:
            raise self._agent_config_too_large(exc.path) from None
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

    def _sync_remote_skills(self, document: BundleDocument) -> None:
        """Materialize declarative ``remote_skills`` beside each agent config."""
        config_paths = ["config.yaml"]
        config_paths.extend(f"agents/{name}/config.yaml" for name in BundleWorkers.names(document))
        requested: dict[str, list[str]] = {}
        for config_path in config_paths:
            config = document.yaml_value(config_path, ())
            if not isinstance(config, Mapping):
                continue
            raw = config.get("remote_skills")
            if raw is None:
                requested[config_path] = []
                continue
            if (
                not isinstance(raw, Sequence)
                or isinstance(raw, str | bytes)
                or any(not isinstance(name, str) or not name for name in raw)
                or len(raw) != len(set(raw))
            ):
                raise BundleValidationFailure(
                    (
                        BundleIssue(
                            "invalid_remote_skills",
                            "remote_skills must be a list of unique non-empty names",
                            file=config_path,
                            path="/remote_skills",
                        ),
                    )
                )
            requested[config_path] = list(raw)

        if not any(requested.values()):
            for config_path in config_paths:
                self._remove_unselected_remote_skills(document, config_path, set())
            return
        for config_path, names in requested.items():
            self._remove_unselected_remote_skills(document, config_path, set(names))
        if self._skills_reader is None:
            if all(
                document.exists(f"{self._skill_root(config_path, name)}/{_REMOTE_SKILL_MARKER}")
                for config_path, names in requested.items()
                for name in names
            ):
                return
            raise BundleValidationFailure(
                (BundleIssue("skills_repository_unavailable", "Skills repository is unavailable"),)
            )

        snapshot = self._skills_reader.load(refresh=False)
        available = {
            skill.name: skill for skill in snapshot.skills if skill.validation_status != "error"
        }
        for config_path, names in requested.items():
            for name in names:
                skill = available.get(name)
                if skill is None:
                    marker = f"{self._skill_root(config_path, name)}/{_REMOTE_SKILL_MARKER}"
                    if document.exists(marker):
                        continue
                    raise BundleValidationFailure(
                        (
                            BundleIssue(
                                "remote_skill_unavailable",
                                f"Remote Skill is unavailable: {name}",
                                file=config_path,
                                path="/remote_skills",
                            ),
                        )
                    )
                self._materialize_remote_skill(
                    document,
                    config_path,
                    skill,
                    snapshot.source.commit_sha,
                )

    @staticmethod
    def _skill_root(config_path: str, name: str) -> str:
        if PurePosixPath(name).name != name or name in {".", ".."} or "\\" in name:
            raise BundleValidationFailure(
                (BundleIssue("invalid_remote_skill_name", "Remote Skill name is not portable"),)
            )
        scope = PurePosixPath(config_path).parent
        prefix = "" if scope.as_posix() == "." else f"{scope.as_posix()}/"
        return f"{prefix}skills/{name}"

    @classmethod
    def _managed_remote_roots(cls, document: BundleDocument, config_path: str) -> set[str]:
        scope = PurePosixPath(config_path).parent
        prefix = "skills/" if scope.as_posix() == "." else f"{scope.as_posix()}/skills/"
        suffix = f"/{_REMOTE_SKILL_MARKER}"
        return {
            path[: -len(suffix)]
            for path in document.paths()
            if path.startswith(prefix)
            and path.endswith(suffix)
            and "/" not in path[len(prefix) : -len(suffix)]
        }

    @classmethod
    def _remove_unselected_remote_skills(
        cls,
        document: BundleDocument,
        config_path: str,
        selected: set[str],
    ) -> None:
        for root in cls._managed_remote_roots(document, config_path):
            if PurePosixPath(root).name in selected:
                continue
            prefix = f"{root}/"
            for path in tuple(document.paths()):
                if path.startswith(prefix):
                    document.delete_file(path)

    @classmethod
    def _materialize_remote_skill(
        cls,
        document: BundleDocument,
        config_path: str,
        skill: SkillRecord,
        commit_sha: str | None,
    ) -> None:
        root = cls._skill_root(config_path, skill.name)
        marker = f"{root}/{_REMOTE_SKILL_MARKER}"
        existing = [path for path in document.paths() if path.startswith(f"{root}/")]
        if existing and marker not in existing:
            raise BundleValidationFailure(
                (
                    BundleIssue(
                        "remote_skill_conflict",
                        f"Remote Skill conflicts with an existing bundled Skill: {skill.name}",
                        file=config_path,
                        path="/remote_skills",
                    ),
                )
            )
        for path in existing:
            document.delete_file(path)
        if not any(file.path == "SKILL.md" for file in skill.files):
            raise BundleValidationFailure(
                (
                    BundleIssue(
                        "remote_skill_unavailable",
                        f"Remote Skill has no readable SKILL.md: {skill.name}",
                        file=config_path,
                        path="/remote_skills",
                    ),
                )
            )
        for file in skill.files:
            document.add_file_bytes(f"{root}/{file.path}", file.content.encode("utf-8"))
        document.add_file_bytes(
            marker,
            (
                json.dumps(
                    {"version": 1, "id": skill.id, "name": skill.name, "commit_sha": commit_sha},
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
        )

    @staticmethod
    def _apply_worker_operation(
        document: BundleDocument,
        operation: BundleWorkerOperation,
    ) -> None:
        try:
            if operation.op == "add":
                if operation.name is None:
                    raise ValueError("worker name is required")
                coordinator = BundleWorkers.coordinator(document)
                config: dict[str, object] = {"spec_version": 1}
                if operation.source == "coordinator":
                    config = copy.deepcopy(coordinator.config)
                    config.pop("tools", None)
                elif "executor" in coordinator.config:
                    config["executor"] = copy.deepcopy(coordinator.config["executor"])
                BundleWorkers.create(document, operation.name, config)
            elif operation.op == "copy":
                if operation.source is None or operation.target is None:
                    raise ValueError("worker source and target are required")
                BundleWorkers.copy(document, operation.source, operation.target)
            elif operation.op == "rename":
                if operation.source is None or operation.target is None:
                    raise ValueError("worker source and target are required")
                BundleWorkers.rename(document, operation.source, operation.target)
            elif operation.op == "delete":
                if operation.name is None:
                    raise ValueError("worker name is required")
                AgentBundleService._delete_worker(
                    document,
                    operation.name,
                    operation.confirmed_references,
                )
        except BundleValidationFailure:
            raise
        except BundleFileSizeError as exc:
            raise AgentBundleService._agent_config_too_large(exc.path) from None
        except Exception:  # noqa: BLE001 - operation boundary must sanitize edit failures
            raise BundleValidationFailure(
                (BundleIssue("invalid_worker_operation", "worker operation could not be applied"),)
            ) from None

    @staticmethod
    def _delete_worker(
        document: BundleDocument,
        worker_name: str,
        confirmed_references: Sequence[str],
    ) -> None:
        references = BundleWorkers.references(document, worker_name)
        confirmed = tuple(confirmed_references)
        confirmed_matches = (
            len(confirmed) == len(set(confirmed)) and tuple(sorted(confirmed)) == references
        )
        if not confirmed_matches:
            issues = tuple(
                BundleIssue(
                    code="worker_references_require_confirmation",
                    message="worker is referenced by another agent configuration",
                    file=reference.partition("#")[0],
                    path=reference.partition("#")[2],
                    worker=worker_name,
                )
                for reference in references
            )
            if not issues:
                issues = (
                    BundleIssue(
                        code="worker_references_confirmation_mismatch",
                        message="confirmed worker references do not match the current bundle",
                    ),
                )
            raise BundleValidationFailure(issues)
        BundleWorkers.delete(document, worker_name)

    def _persist_update(
        self,
        agent: Agent,
        document: BundleDocument,
        *,
        expected_version: int,
        name: str,
        description: str | None,
    ) -> BundleDetail:
        self._sync_remote_skills(document)
        self._require_inline_agent_configs(document)
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
        document = self._load_document(agent)
        self._require_inline_agent_configs(document)
        return agent, document

    def _require_agent(self, agent_id: str) -> Agent:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"agent bundle {agent_id!r} not found")
        return agent

    @staticmethod
    def _require_editable(agent: Agent) -> None:
        if AgentBundleService._is_builtin(agent):
            raise PermissionError("built-in agent bundle is read-only")

    @staticmethod
    def _is_builtin(agent: Agent) -> bool:
        return agent.session_id is None and agent.id == builtin_agent_id(agent.name)

    def _load_document(self, agent: Agent) -> BundleDocument:
        return BundleDocument.from_bytes(self._artifacts.get(agent.bundle_location))

    def _detail(self, agent: Agent, document: BundleDocument) -> BundleDetail:
        self._require_inline_agent_configs(document)
        remaining = _MAX_INLINE_TOTAL_BYTES
        files: list[BundleFile] = []
        diagnostics: list[BundleIssue] = []
        for path in document.paths():
            size = document.file_size(path)
            inline = size <= _MAX_INLINE_FILE_BYTES and size <= remaining
            files.append(self._file(document, path, inline=inline))
            if inline:
                remaining -= size
            else:
                diagnostics.append(
                    BundleIssue(
                        code="file_not_inlined",
                        message="file exceeds the inline response limit",
                        file=path,
                    )
                )
        return BundleDetail(
            card=self._card(agent, document),
            coordinator=BundleWorkers.coordinator(document),
            workers=tuple(BundleWorkers.list(document)),
            files=tuple(files),
            diagnostics=tuple(diagnostics),
        )

    @staticmethod
    def _agent_config_limit_issue(document: BundleDocument) -> BundleIssue | None:
        paths = ["config.yaml"] if document.exists("config.yaml") else []
        paths.extend(
            path
            for path in document.paths()
            if path.startswith("agents/") and path.endswith("/config.yaml")
        )
        total = 0
        for path in paths:
            size = document.file_size(path)
            if size > _MAX_INLINE_FILE_BYTES:
                return BundleIssue(
                    code="agent_config_too_large",
                    message="agent configuration exceeds the safe response limit",
                    file=path,
                )
            total += size
            if total > _MAX_INLINE_TOTAL_BYTES:
                return BundleIssue(
                    code="agent_configs_too_large",
                    message="agent configurations exceed the safe response limit",
                    file=path,
                )
        return None

    @classmethod
    def _require_inline_agent_configs(cls, document: BundleDocument) -> None:
        issue = cls._agent_config_limit_issue(document)
        if issue is not None:
            raise BundleValidationFailure((issue,))

    @staticmethod
    def _require_agent_config_text(path: str, content: str) -> None:
        if len(content.encode("utf-8")) > _MAX_INLINE_FILE_BYTES:
            raise BundleValidationFailure(
                (
                    BundleIssue(
                        code="agent_config_too_large",
                        message="agent configuration exceeds the safe response limit",
                        file=path,
                    ),
                )
            )

    @staticmethod
    def _agent_config_too_large(path: str) -> BundleValidationFailure:
        return BundleValidationFailure(
            (
                BundleIssue(
                    code="agent_config_too_large",
                    message="agent configuration exceeds the safe response limit",
                    file=path,
                ),
            )
        )

    @staticmethod
    def _file(document: BundleDocument, path: str, *, inline: bool = True) -> BundleFile:
        size = document.file_size(path)
        if not inline:
            media_type = mimetypes.guess_type(path)[0]
            if path.endswith((".yaml", ".yml")):
                media_type = "application/yaml"
            elif path.endswith(".md"):
                media_type = "text/markdown"
            return BundleFile(
                path=path,
                content=None,
                encoding="binary",
                media_type=media_type,
                size=size,
                inline=False,
            )
        raw = document.read_bytes(path)
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = None
        data: object | None = None
        if content is not None and path.endswith((".yaml", ".yml")):
            try:
                data = document.yaml_value(path, ())
            except Exception:  # noqa: BLE001 - diagnostics own invalid YAML details
                data = None
        media_type = mimetypes.guess_type(path)[0]
        if path.endswith((".yaml", ".yml")):
            media_type = "application/yaml"
        elif path.endswith(".md"):
            media_type = "text/markdown"
        return BundleFile(
            path=path,
            content=content,
            encoding="utf-8" if content is not None else "binary",
            media_type=media_type,
            size=len(raw),
            data=data,
            inline=True,
        )

    @staticmethod
    def _card(agent: Agent, document: BundleDocument) -> BundleCard:
        digest = agent.bundle_location.rsplit("/", 1)[-1]
        config = BundleWorkers.coordinator(document).config
        executor = config.get("executor")
        executor_config = executor.get("config") if isinstance(executor, Mapping) else None
        harness = executor_config.get("harness") if isinstance(executor_config, Mapping) else None
        tools = config.get("tools")
        mcp = config.get("mcp") or config.get("mcp_servers")
        if mcp is None and isinstance(tools, Mapping):
            mcp = tools.get("mcp")
        builtin = AgentBundleService._is_builtin(agent)
        return BundleCard(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            version=agent.version,
            digest=digest,
            readonly=builtin,
            harness=harness if isinstance(harness, str) else None,
            worker_count=len(BundleWorkers.names(document)),
            skill_count=sum(
                path.startswith("skills/") and path.endswith("/SKILL.md")
                for path in document.paths()
            ),
            mcp_count=AgentBundleService._collection_count(mcp),
            validation_status="valid",
            updated_at=agent.updated_at if agent.updated_at is not None else agent.created_at,
            builtin=builtin,
            editable=not builtin,
        )

    @staticmethod
    def _collection_count(value: object) -> int:
        if isinstance(value, Mapping | Sequence) and not isinstance(value, str | bytes):
            return len(value)
        return 0 if value is None else 1

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
                    file=path,
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
    "BundleFile",
    "BundleIssue",
    "BundlePage",
    "BundleValidationFailure",
    "BundleValidationResult",
    "BundleWorkerOperation",
]
