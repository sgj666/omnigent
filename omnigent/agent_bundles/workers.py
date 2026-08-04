"""Atomic coordinator and worker edits for Agent Bundles."""

from __future__ import annotations

import copy
import io
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ruamel.yaml import YAML

from omnigent.agent_bundles.document import BundleDocument
from omnigent.agent_bundles.patches import BundlePatch, apply_patches

_CONFIG_PATH = "config.yaml"
_WORKER_NAME = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class BundleAgentView:
    """One coordinator or worker configuration plus its lossless YAML source."""

    name: str
    config: dict[str, Any]
    advanced_yaml: str


class BundleWorkers:
    """Edit the official ``tools.agents`` / ``agents/<name>/`` structure."""

    @classmethod
    def coordinator(cls, document: BundleDocument) -> BundleAgentView:
        config = cls._config(document, _CONFIG_PATH)
        name = config.get("name")
        return BundleAgentView(
            name=name if isinstance(name, str) else "",
            config=config,
            advanced_yaml=document.read_text(_CONFIG_PATH),
        )

    @classmethod
    def update_coordinator(
        cls,
        document: BundleDocument,
        changes: Mapping[str, object],
    ) -> None:
        candidate = document.clone()
        cls._apply_changes(candidate, _CONFIG_PATH, changes)
        document.swap(candidate)

    @classmethod
    def names(cls, document: BundleDocument) -> list[str]:
        config = cls._config(document, _CONFIG_PATH)
        tools = config.get("tools")
        if tools is None:
            return []
        if not isinstance(tools, Mapping):
            raise ValueError("coordinator tools must be a mapping")
        agents = tools.get("agents")
        if agents is None:
            return []
        if not isinstance(agents, Sequence) or isinstance(agents, str | bytes):
            raise ValueError("coordinator tools.agents must be a sequence")
        names = list(agents)
        if any(not isinstance(name, str) for name in names):
            raise ValueError("coordinator tools.agents must contain worker names")
        return names

    @classmethod
    def list(cls, document: BundleDocument) -> list[BundleAgentView]:
        return [cls.get(document, name) for name in cls.names(document)]

    @classmethod
    def get(cls, document: BundleDocument, name: str) -> BundleAgentView:
        cls._validate_name(name)
        if name not in cls.names(document):
            raise KeyError(name)
        path = cls._worker_config_path(name)
        config = cls._config(document, path)
        return BundleAgentView(
            name=name,
            config=config,
            advanced_yaml=document.read_text(path),
        )

    @classmethod
    def create(
        cls,
        document: BundleDocument,
        name: str,
        config: Mapping[str, object],
    ) -> None:
        cls._validate_name(name)
        current = cls.names(document)
        if name in current:
            raise ValueError(f"worker already exists: {name!r}")
        rendered_config = copy.deepcopy(dict(config))
        rendered_config["name"] = name

        candidate = document.clone()
        cls._set_roster(candidate, [*current, name])
        candidate.add_file_bytes(
            cls._worker_config_path(name),
            cls._render_yaml(rendered_config).encode("utf-8"),
        )
        document.swap(candidate)

    @classmethod
    def update(
        cls,
        document: BundleDocument,
        name: str,
        changes: Mapping[str, object],
    ) -> None:
        cls.get(document, name)
        requested_name = changes.get("name")
        if requested_name is not None and requested_name != name:
            raise ValueError("worker name cannot be changed by update")
        effective = {key: value for key, value in changes.items() if key != "name"}
        candidate = document.clone()
        cls._apply_changes(candidate, cls._worker_config_path(name), effective)
        document.swap(candidate)

    @classmethod
    def delete(cls, document: BundleDocument, name: str) -> None:
        cls.get(document, name)
        candidate = document.clone()
        cls._set_roster(candidate, [worker for worker in cls.names(document) if worker != name])
        prefix = f"agents/{name}/"
        for path in candidate.paths():
            if path.startswith(prefix):
                candidate.delete_file(path)
        document.swap(candidate)

    @classmethod
    def references(cls, document: BundleDocument, name: str) -> tuple[str, ...]:
        """Return stable structured references to a worker outside its own config."""
        cls.get(document, name)
        references: list[str] = []
        config_paths = [_CONFIG_PATH]
        config_paths.extend(
            cls._worker_config_path(worker) for worker in cls.names(document) if worker != name
        )
        for path in config_paths:
            config = cls._config(document, path)
            cls._collect_references(config, name, path, (), references)
        return tuple(sorted(references))

    @classmethod
    def _collect_references(
        cls,
        value: object,
        name: str,
        file: str,
        pointer: tuple[str | int, ...],
        references: list[str],
    ) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if not isinstance(key, str):
                    continue
                child_pointer = (*pointer, key)
                if key == "agents" and pointer and pointer[-1] == "tools":
                    if file == _CONFIG_PATH and pointer == ("tools",):
                        continue
                    if isinstance(child, Sequence) and not isinstance(child, str | bytes):
                        for index, candidate in enumerate(child):
                            if candidate == name:
                                references.append(
                                    f"{file}#{cls._json_pointer((*child_pointer, index))}"
                                )
                    continue
                if (
                    key
                    in {
                        "agent",
                        "worker",
                        "agent_name",
                        "worker_name",
                        "target_agent",
                        "delegate_to",
                    }
                    and child == name
                ):
                    references.append(f"{file}#{cls._json_pointer(child_pointer)}")
                else:
                    cls._collect_references(child, name, file, child_pointer, references)
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            for index, child in enumerate(value):
                cls._collect_references(child, name, file, (*pointer, index), references)

    @classmethod
    def _json_pointer(cls, pointer: Sequence[str | int]) -> str:
        return "/" + "/".join(
            str(component) if isinstance(component, int) else cls._pointer_token(component)
            for component in pointer
        )

    @classmethod
    def copy(cls, document: BundleDocument, source: str, target: str) -> None:
        """Copy a worker's complete directory and append the copy to the roster."""
        cls.get(document, source)
        cls._validate_name(target)
        current = cls.names(document)
        if target in current:
            raise ValueError(f"worker already exists: {target!r}")
        candidate = document.clone()
        cls._copy_tree(candidate, source, target)
        cls._set_roster(candidate, [*current, target])
        apply_patches(
            candidate,
            [BundlePatch(cls._worker_config_path(target), "replace", "/name", target)],
        )
        document.swap(candidate)

    @classmethod
    def rename(cls, document: BundleDocument, source: str, target: str) -> None:
        """Rename a worker directory and roster entry without changing its position."""
        cls.get(document, source)
        cls._validate_name(target)
        current = cls.names(document)
        if target in current:
            raise ValueError(f"worker already exists: {target!r}")
        candidate = document.clone()
        cls._copy_tree(candidate, source, target)
        apply_patches(
            candidate,
            [BundlePatch(cls._worker_config_path(target), "replace", "/name", target)],
        )
        cls._set_roster(
            candidate,
            [target if worker == source else worker for worker in current],
        )
        for path in candidate.paths():
            if path.startswith(f"agents/{source}/"):
                candidate.delete_file(path)
        document.swap(candidate)

    @classmethod
    def reorder(cls, document: BundleDocument, names: Sequence[str]) -> None:
        requested = list(names)
        current = cls.names(document)
        if len(requested) != len(current) or set(requested) != set(current):
            raise ValueError("worker order must contain every existing worker exactly once")
        candidate = document.clone()
        cls._set_roster(candidate, requested)
        document.swap(candidate)

    @classmethod
    def replace_advanced_yaml(
        cls,
        document: BundleDocument,
        name: str | None,
        advanced_yaml: str,
    ) -> None:
        path = _CONFIG_PATH if name is None else cls._worker_config_path(name)
        if name is not None:
            cls.get(document, name)
        candidate = document.clone()
        candidate.replace_file_bytes(path, advanced_yaml.encode("utf-8"))
        cls._config(candidate, path)
        document.swap(candidate)

    @staticmethod
    def _validate_name(name: str) -> None:
        if not isinstance(name, str) or _WORKER_NAME.fullmatch(name) is None:
            raise ValueError("worker name must match [A-Za-z0-9_-]+")

    @staticmethod
    def _worker_config_path(name: str) -> str:
        return f"agents/{name}/config.yaml"

    @staticmethod
    def _copy_tree(document: BundleDocument, source: str, target: str) -> None:
        source_prefix = f"agents/{source}/"
        target_prefix = f"agents/{target}/"
        for path in document.paths():
            if path.startswith(source_prefix):
                document.add_file_bytes(
                    f"{target_prefix}{path.removeprefix(source_prefix)}",
                    document.read_bytes(path),
                )

    @staticmethod
    def _config(document: BundleDocument, path: str) -> dict[str, Any]:
        value = document.yaml_value(path, ())
        if not isinstance(value, Mapping):
            raise ValueError(f"bundle config must be a mapping: {path}")
        return dict(value)

    @classmethod
    def _set_roster(cls, document: BundleDocument, names: list[str]) -> None:
        config = cls._config(document, _CONFIG_PATH)
        tools = config.get("tools")
        if tools is None:
            patches = [BundlePatch(_CONFIG_PATH, "add", "/tools", {"agents": names})]
        elif not isinstance(tools, Mapping):
            raise ValueError("coordinator tools must be a mapping")
        elif "agents" not in tools:
            patches = [BundlePatch(_CONFIG_PATH, "add", "/tools/agents", names)]
        else:
            patches = [BundlePatch(_CONFIG_PATH, "replace", "/tools/agents", names)]
        apply_patches(document, patches)

    @classmethod
    def _apply_changes(
        cls,
        document: BundleDocument,
        path: str,
        changes: Mapping[str, object],
    ) -> None:
        patches = [
            BundlePatch(path, "add", f"/{cls._pointer_token(key)}", copy.deepcopy(value))
            for key, value in changes.items()
        ]
        apply_patches(document, patches)

    @staticmethod
    def _pointer_token(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("bundle config field names must be strings")
        return value.replace("~", "~0").replace("/", "~1")

    @staticmethod
    def _render_yaml(value: Mapping[str, object]) -> str:
        stream = io.StringIO()
        yaml = YAML(typ="rt")
        yaml.dump(dict(value), stream)
        return stream.getvalue()
