"""Safe, lossless editing of gzipped Agent Template bundles."""

from __future__ import annotations

import copy
import gzip
import io
import re
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Self

from ruamel.yaml import YAML
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from ruamel.yaml.scalarstring import (
    DoubleQuotedScalarString,
    FoldedScalarString,
    LiteralScalarString,
    SingleQuotedScalarString,
)
from ruamel.yaml.tokens import (
    AliasToken,
    BlockEntryToken,
    BlockSequenceStartToken,
    DocumentStartToken,
    FlowEntryToken,
    FlowMappingEndToken,
    FlowMappingStartToken,
    FlowSequenceEndToken,
    FlowSequenceStartToken,
    ValueToken,
)

from omnigent.spec.tar_utils import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_ENTRIES,
    ExtractionError,
    extract_safe,
)

YamlPointer = Sequence[str | int]


@dataclass(frozen=True)
class _YamlLocation:
    value: Any
    node: Node
    parent: _YamlLocation | None = None
    component: str | int | None = None
    key_node: Node | None = None
    index: int | None = None
    alias_token: AliasToken | None = None


def _normalize_posix_path(path: str) -> str:
    try:
        path.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"bundle path must be valid UTF-8: {path!r}") from exc
    if "\x00" in path:
        raise ValueError(f"bundle path must not contain NUL: {path!r}")
    if "\\" in path:
        raise ValueError(f"bundle path must use POSIX separators: {path!r}")
    if re.match(r"^[A-Za-z]:", path):
        raise ValueError(f"bundle path must not use a Windows drive: {path!r}")

    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"bundle path must stay within the archive: {path!r}")
    normalized = candidate.as_posix()
    if normalized in {"", "."}:
        raise ValueError("bundle path must name a file or directory")
    return normalized


def _validate_nul_padding(raw: bytes | bytearray, *, field: str) -> None:
    nul_index = raw.find(b"\x00")
    if nul_index >= 0 and any(raw[nul_index + 1 :]):
        raise ExtractionError(f"tarball contains non-padding data after NUL in {field}")


class _RawNameValidatingTarInfo(tarfile.TarInfo):
    """Reject archive names that tarfile would silently truncate at NUL."""

    @classmethod
    def frombuf(
        cls,
        buf: bytes | bytearray,
        encoding: str,
        errors: str,
    ) -> Self:
        if len(buf) == tarfile.BLOCKSIZE:
            _validate_nul_padding(buf[0:100], field="USTAR name")
            _validate_nul_padding(buf[345:500], field="USTAR prefix")
        return super().frombuf(buf, encoding, errors)

    def _proc_gnulong(self, archive: tarfile.TarFile) -> tarfile.TarInfo:
        if self.size < 0:
            raise ExtractionError("tarball contains an invalid GNU longname size")
        if self.size > DEFAULT_MAX_BYTES:
            raise ExtractionError(
                f"tarball exceeds max extracted size ({DEFAULT_MAX_BYTES} bytes)"
            )
        padded_size = (self.size + tarfile.BLOCKSIZE - 1) // tarfile.BLOCKSIZE * tarfile.BLOCKSIZE
        payload = archive.fileobj.read(padded_size)
        if self.type == tarfile.GNUTYPE_LONGNAME:
            _validate_nul_padding(payload[: self.size], field="GNU longname")

        try:
            next_member = self.fromtarfile(archive)
        except tarfile.HeaderError as exc:
            raise ExtractionError(f"invalid tarball after GNU longname: {exc}") from exc

        next_member.offset = self.offset
        decoded = payload.partition(b"\x00")[0].decode(archive.encoding, archive.errors)
        if self.type == tarfile.GNUTYPE_LONGNAME:
            next_member.name = decoded
        elif self.type == tarfile.GNUTYPE_LONGLINK:
            next_member.linkname = decoded
        if next_member.isdir():
            next_member.name = next_member.name.removesuffix("/")
        return next_member


def _register_namespace_path(
    path: str,
    member_type: str,
    seen: dict[str, str],
    required_directories: set[str],
) -> None:
    if path in seen:
        if seen[path] != member_type:
            raise ValueError(f"bundle contains conflicting file and directory entries: {path!r}")
        raise ValueError(f"bundle contains a duplicate normalized path: {path!r}")

    ancestors = tuple(
        parent.as_posix() for parent in PurePosixPath(path).parents if parent.as_posix() != "."
    )
    file_ancestor = next(
        (ancestor for ancestor in ancestors if seen.get(ancestor) == "file"),
        None,
    )
    if file_ancestor is not None:
        raise ValueError(
            f"bundle contains conflicting paths: file {file_ancestor!r} is an ancestor of {path!r}"
        )
    if member_type == "file" and path in required_directories:
        raise ValueError(
            f"bundle contains conflicting paths: file {path!r} is the parent of another member"
        )

    seen[path] = member_type
    required_directories.update(ancestors)


def _normalize_files(files: Mapping[str, bytes]) -> dict[str, bytes]:
    normalized_files: dict[str, bytes] = {}
    seen: dict[str, str] = {}
    required_directories: set[str] = set()
    for path, content in files.items():
        normalized = _normalize_posix_path(path)
        _register_namespace_path(normalized, "file", seen, required_directories)
        normalized_files[normalized] = content
    return normalized_files


class BundleDocument:
    """An in-memory bundle file tree with round-trip YAML editing."""

    def __init__(self, files: Mapping[str, bytes]) -> None:
        self._files = _normalize_files(files)
        self._yaml_documents: dict[str, Any] = {}

    @classmethod
    def from_bytes(cls, bundle: bytes) -> BundleDocument:
        """Open untrusted tar bytes after applying the shared safety limits."""
        cls._preflight_archive(bundle)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            extract_safe(bundle, root)
            files = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
        return cls(files)

    @staticmethod
    def _preflight_archive(bundle: bytes) -> None:
        seen: dict[str, str] = {}
        required_directories: set[str] = set()
        total_bytes = 0
        try:
            with tarfile.open(
                fileobj=io.BytesIO(bundle),
                mode="r:*",
                tarinfo=_RawNameValidatingTarInfo,
            ) as archive:
                for entry_count, member in enumerate(archive, start=1):
                    if entry_count > DEFAULT_MAX_ENTRIES:
                        raise ExtractionError(
                            f"tarball exceeds max entry count ({DEFAULT_MAX_ENTRIES})"
                        )

                    try:
                        normalized = _normalize_posix_path(member.name)
                    except ValueError as exc:
                        raise ExtractionError(str(exc)) from exc

                    if member.isfile():
                        member_type = "file"
                        total_bytes += member.size
                        if total_bytes > DEFAULT_MAX_BYTES:
                            raise ExtractionError(
                                f"tarball exceeds max extracted size ({DEFAULT_MAX_BYTES} bytes)"
                            )
                    elif member.isdir():
                        member_type = "directory"
                    else:
                        raise ExtractionError(
                            "tarball contains an unsupported entry type "
                            f"(only regular files and directories are allowed): {member.name!r}"
                        )

                    try:
                        _register_namespace_path(
                            normalized,
                            member_type,
                            seen,
                            required_directories,
                        )
                    except ValueError as exc:
                        raise ExtractionError(str(exc)) from exc
        except (tarfile.ReadError, tarfile.CompressionError) as exc:
            raise ExtractionError(f"invalid tarball: {exc}") from exc

    def exists(self, path: str) -> bool:
        """Return whether *path* is a regular file in the bundle."""
        return _normalize_posix_path(path) in self._files

    def paths(self) -> tuple[str, ...]:
        """Return the bundle's normalized regular-file paths in sorted order."""
        return tuple(sorted(self._files))

    def read_text(self, path: str) -> str:
        """Read one UTF-8 bundle file without changing its bytes."""
        return self._files[_normalize_posix_path(path)].decode("utf-8")

    def yaml_value(self, path: str, pointer: YamlPointer) -> Any:
        """Return a detached value at a tuple-style YAML pointer."""
        value = self._yaml_document(path)
        for component in pointer:
            value = self._child(value, component)
        return copy.deepcopy(value)

    def replace_yaml_value(self, path: str, pointer: YamlPointer, value: object) -> None:
        """Replace an existing YAML value while preserving presentation details."""
        normalized = _normalize_posix_path(path)
        replacement = copy.deepcopy(value)
        if not pointer:
            rendered = self._render_document(replacement)
        else:
            try:
                source, location = self._yaml_location(normalized, pointer)
            except KeyError:
                source, parent = self._yaml_location(normalized, pointer[:-1])
                component = pointer[-1]
                if not isinstance(parent.value, Mapping) or component not in parent.value:
                    raise
                rendered = self._add_mapping_source_value(
                    source,
                    parent,
                    component,
                    replacement,
                )
            else:
                rendered = self._replace_source_value(source, location, replacement)

        self._commit_yaml_source(normalized, rendered)

    def add_yaml_value(self, path: str, pointer: YamlPointer, value: object) -> None:
        """Add a YAML mapping member or sequence item."""
        normalized = _normalize_posix_path(path)
        replacement = copy.deepcopy(value)
        if not pointer:
            rendered = self._render_document(replacement)
        else:
            source, parent = self._yaml_location(normalized, pointer[:-1])
            component = pointer[-1]
            if isinstance(parent.value, Mapping):
                if component in parent.value:
                    try:
                        _, target = self._yaml_location(normalized, pointer)
                    except KeyError:
                        rendered = self._add_mapping_source_value(
                            source,
                            parent,
                            component,
                            replacement,
                        )
                    else:
                        rendered = self._replace_source_value(source, target, replacement)
                else:
                    rendered = self._add_mapping_source_value(
                        source,
                        parent,
                        component,
                        replacement,
                    )
            elif isinstance(parent.value, Sequence) and not isinstance(parent.value, str | bytes):
                index = (
                    len(parent.value)
                    if component == "-"
                    else self._sequence_add_index(parent.value, component)
                )
                rendered = self._add_sequence_source_value(
                    source,
                    parent,
                    index,
                    replacement,
                )
            else:
                raise TypeError(
                    f"YAML pointer cannot add a child to {type(parent.value).__name__}"
                )

        self._commit_yaml_source(normalized, rendered)

    def remove_yaml_value(self, path: str, pointer: YamlPointer) -> None:
        """Remove an existing YAML mapping member or sequence item."""
        if not pointer:
            raise ValueError("cannot remove the YAML document root")
        normalized = _normalize_posix_path(path)
        source, target = self._yaml_location(normalized, pointer)
        assert target.parent is not None
        rendered = self._remove_source_value(source, target.parent, target)

        self._commit_yaml_source(normalized, rendered)

    def replace_file_bytes(self, path: str, data: bytes) -> None:
        """Replace an existing bundle file with raw bytes."""
        normalized = _normalize_posix_path(path)
        if normalized not in self._files:
            raise KeyError(normalized)
        self._files[normalized] = data
        self._yaml_documents.pop(normalized, None)

    def add_file_bytes(self, path: str, data: bytes) -> None:
        """Add a new regular file without exposing the mutable file mapping."""
        normalized = _normalize_posix_path(path)
        if normalized in self._files:
            raise ValueError(f"bundle file already exists: {normalized!r}")
        candidate = dict(self._files)
        candidate[normalized] = data
        self._files = _normalize_files(candidate)

    def delete_file(self, path: str) -> None:
        """Delete an existing file from the bundle."""
        normalized = _normalize_posix_path(path)
        del self._files[normalized]
        self._yaml_documents.pop(normalized, None)

    def _commit_yaml_source(self, normalized: str, rendered: str) -> None:
        encoded = rendered.encode("utf-8")
        self._validate_yaml_candidate(encoded)
        self._files[normalized] = encoded
        self._yaml_documents.pop(normalized, None)

    @classmethod
    def _render_document(cls, value: object) -> str:
        stream = io.StringIO()
        cls._dump_yaml().dump(value, stream)
        return stream.getvalue()

    @staticmethod
    def _validate_yaml_candidate(rendered: bytes) -> None:
        text = rendered.decode("utf-8")
        BundleDocument._yaml().load(text)
        YAML(typ="safe").compose(text)

    def clone(self) -> BundleDocument:
        """Return a fully independent copy suitable for atomic edits."""
        clone = BundleDocument(self._files)
        clone._yaml_documents = copy.deepcopy(self._yaml_documents)
        return clone

    def swap(self, other: BundleDocument) -> None:
        """Replace this document with an independent snapshot of *other*."""
        files = dict(other._files)
        yaml_documents = copy.deepcopy(other._yaml_documents)
        self._files = files
        self._yaml_documents = yaml_documents

    def to_bytes(self) -> bytes:
        """Serialize a deterministic gzip-compressed tar archive."""
        files = _normalize_files(self._files)
        output = io.BytesIO()
        with (
            gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed,
            tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive,
        ):
            for path in sorted(files):
                data = files[path]
                member = tarfile.TarInfo(path)
                member.size = len(data)
                member.mode = 0o644
                member.uid = 0
                member.gid = 0
                member.uname = ""
                member.gname = ""
                member.mtime = 0
                archive.addfile(member, io.BytesIO(data))
        return output.getvalue()

    def _yaml_document(self, path: str) -> Any:
        normalized = _normalize_posix_path(path)
        if normalized not in self._yaml_documents:
            self._yaml_documents[normalized] = self._yaml().load(self.read_text(normalized))
        return self._yaml_documents[normalized]

    @staticmethod
    def _yaml() -> YAML:
        yaml = YAML(typ="rt")
        yaml.preserve_quotes = True
        return yaml

    @classmethod
    def _dump_yaml(cls, *, flow: bool | None = None) -> YAML:
        yaml = cls._yaml()
        yaml.default_flow_style = flow
        yaml.representer.add_representer(
            type(None),
            lambda representer, _: representer.represent_scalar(
                "tag:yaml.org,2002:null",
                "null",
            ),
        )
        return yaml

    def _yaml_location(
        self,
        normalized: str,
        pointer: YamlPointer,
    ) -> tuple[str, _YamlLocation]:
        source = self.read_text(normalized)
        value = self._yaml_document(normalized)
        node = self._yaml().compose(source)
        if node is None:
            raise TypeError("YAML pointer cannot traverse an empty document")
        location = _YamlLocation(value=value, node=node)
        for component in pointer:
            if location.alias_token is not None:
                raise ValueError("cannot traverse a YAML alias occurrence")
            if isinstance(location.value, Mapping):
                if component not in location.value:
                    raise KeyError(component)
                assert isinstance(location.node, MappingNode)
                pair = next(
                    (
                        (index, key_node, child_node)
                        for index, (key_node, child_node) in enumerate(location.node.value)
                        if isinstance(key_node, ScalarNode) and key_node.value == component
                    ),
                    None,
                )
                if pair is None:
                    raise KeyError(component)
                index, key_node, child_node = pair
                location = _YamlLocation(
                    value=location.value[component],
                    node=child_node,
                    parent=location,
                    component=component,
                    key_node=key_node,
                    index=index,
                    alias_token=self._mapping_alias_token(
                        source,
                        location.node,
                        index,
                        child_node,
                    ),
                )
                continue
            if isinstance(location.value, Sequence) and not isinstance(
                location.value, str | bytes
            ):
                index = self._sequence_index(location.value, component)
                assert isinstance(location.node, SequenceNode)
                child_node = location.node.value[index]
                location = _YamlLocation(
                    value=location.value[index],
                    node=child_node,
                    parent=location,
                    component=index,
                    index=index,
                    alias_token=self._sequence_alias_token(
                        source,
                        location.node,
                        index,
                        child_node,
                    ),
                )
                continue
            raise TypeError(f"YAML pointer cannot traverse {type(location.value).__name__}")
        return source, location

    @classmethod
    def _mapping_alias_token(
        cls,
        source: str,
        mapping: MappingNode,
        index: int,
        child: Node,
    ) -> AliasToken | None:
        key = mapping.value[index][0]
        occurrence_end = (
            mapping.value[index + 1][0].start_mark.index
            if index + 1 < len(mapping.value)
            else mapping.end_mark.index
        )
        if key.end_mark.index <= child.start_mark.index < occurrence_end:
            return None
        aliases = [
            token
            for token in cls._yaml().scan(source)
            if isinstance(token, AliasToken)
            and key.end_mark.index <= token.start_mark.index < occurrence_end
        ]
        if len(aliases) != 1:
            raise ValueError("could not locate YAML alias occurrence")
        return aliases[0]

    @classmethod
    def _sequence_alias_token(
        cls,
        source: str,
        sequence: SequenceNode,
        index: int,
        child: Node,
    ) -> AliasToken | None:
        occurrence_start, occurrence_end = cls._sequence_entry_bounds(
            source,
            sequence,
            index,
        )
        if occurrence_start <= child.start_mark.index < occurrence_end:
            return None
        aliases = [
            token
            for token in cls._yaml().scan(source)
            if isinstance(token, AliasToken)
            and occurrence_start <= token.start_mark.index < occurrence_end
        ]
        if len(aliases) != 1:
            raise ValueError("could not locate YAML alias occurrence")
        return aliases[0]

    @classmethod
    def _replace_source_value(
        cls,
        source: str,
        location: _YamlLocation,
        value: object,
    ) -> str:
        assert location.parent is not None
        parent = location.parent
        start_mark = (
            location.alias_token.start_mark
            if location.alias_token is not None
            else location.node.start_mark
        )
        end_mark = (
            location.alias_token.end_mark
            if location.alias_token is not None
            else location.node.end_mark
        )
        if location.alias_token is None:
            value = cls._with_scalar_style(location.node, value)
        flow = bool(getattr(parent.node, "flow_style", False))
        if flow:
            fragment = cls._render_value_fragment(value, flow=True)
        else:
            fragment = cls._render_value_fragment(value, flow=False)
            if isinstance(parent.node, MappingNode) and location.key_node is not None:
                same_line = location.key_node.start_mark.line == start_mark.line
                if (
                    same_line
                    and isinstance(value, Mapping | Sequence)
                    and not isinstance(value, str | bytes)
                ):
                    fragment = cls._render_value_fragment(value, flow=True)
            fragment = cls._indent_fragment_continuation(
                fragment,
                start_mark.column,
            )
        fragment = fragment.replace(
            "\n",
            cls._newline_style(source, start_mark.index),
        )
        return cls._splice_source(
            source,
            [(start_mark.index, end_mark.index, fragment)],
        )

    @staticmethod
    def _with_scalar_style(node: Node, value: object) -> object:
        if not isinstance(node, ScalarNode) or not isinstance(value, str):
            return value
        scalar_type = {
            '"': DoubleQuotedScalarString,
            "'": SingleQuotedScalarString,
            "|": LiteralScalarString,
            ">": FoldedScalarString,
        }.get(node.style)
        return scalar_type(value) if scalar_type is not None else value

    @classmethod
    def _add_mapping_source_value(
        cls,
        source: str,
        parent: _YamlLocation,
        component: str | int,
        value: object,
    ) -> str:
        assert isinstance(parent.node, MappingNode)
        if parent.node.flow_style:
            fragment = cls._render_mapping_entry(component, value, flow=True)
            insertion, footer = cls._flow_end_insertion(source, parent)
            if footer:
                suffix = ", "
                prefix = "" if cls._preceding_non_whitespace(source, insertion) in "{," else ", "
            else:
                suffix = ""
                prefix = "" if not parent.node.value else ", "
            return cls._splice_source(
                source,
                [(insertion, insertion, prefix + fragment + suffix)],
            )

        fragment = cls._render_mapping_entry(component, value, flow=False)
        indent = (
            parent.node.value[0][0].start_mark.column
            if parent.node.value
            else parent.node.start_mark.column
        )
        fragment = cls._indent_fragment(fragment, indent) + "\n"
        if parent.node.value:
            last_index = len(parent.node.value) - 1
            last_value = parent.node.value[last_index][1]
            last_alias = cls._mapping_alias_token(
                source,
                parent.node,
                last_index,
                last_value,
            )
            content_end = (
                last_alias.end_mark.index
                if last_alias is not None
                else cls._node_content_end(last_value)
            )
            insertion = cls._line_end(
                source,
                content_end - 1,
            )
            insertion = cls._deep_child_footer_end(source, insertion, indent)
        else:
            insertion = parent.node.end_mark.index
        fragment = cls._block_insertion_fragment(source, insertion, fragment)
        return cls._splice_source(source, [(insertion, insertion, fragment)])

    @classmethod
    def _add_sequence_source_value(
        cls,
        source: str,
        parent: _YamlLocation,
        index: int,
        value: object,
    ) -> str:
        assert isinstance(parent.node, SequenceNode)
        if parent.node.flow_style:
            fragment = cls._render_sequence_item(value, flow=True)
            if not parent.value:
                insertion, footer = cls._flow_end_insertion(source, parent)
                suffix = ", " if footer else ""
                return cls._splice_source(source, [(insertion, insertion, fragment + suffix)])
            if index == len(parent.value):
                insertion, footer = cls._flow_end_insertion(source, parent)
                if footer and cls._preceding_non_whitespace(source, insertion) == ",":
                    replacement = fragment + ", "
                else:
                    replacement = ", " + fragment
                return cls._splice_source(source, [(insertion, insertion, replacement)])
            successor = parent.node.value[index]
            successor_alias = cls._sequence_alias_token(
                source,
                parent.node,
                index,
                successor,
            )
            successor_start = (
                successor_alias.start_mark.index
                if successor_alias is not None
                else successor.start_mark.index
            )
            insertion = cls._token_pre_comment_start(
                source,
                successor_start,
            )
            return cls._splice_source(source, [(insertion, insertion, fragment + ", ")])

        indent = parent.node.start_mark.column
        fragment = cls._indent_fragment(cls._render_sequence_item(value, flow=False), indent)
        fragment += "\n"
        if index == 0:
            insertion = cls._first_block_sequence_insertion(source, parent)
        else:
            previous = parent.node.value[index - 1]
            previous_alias = cls._sequence_alias_token(
                source,
                parent.node,
                index - 1,
                previous,
            )
            content_end = (
                previous_alias.end_mark.index
                if previous_alias is not None
                else cls._node_content_end(previous)
            )
            insertion = cls._line_end(
                source,
                content_end - 1,
            )
            if index == len(parent.value):
                insertion = cls._deep_child_footer_end(source, insertion, indent)
        fragment = cls._block_insertion_fragment(source, insertion, fragment)
        return cls._splice_source(source, [(insertion, insertion, fragment)])

    @classmethod
    def _remove_source_value(
        cls,
        source: str,
        parent: _YamlLocation,
        target: _YamlLocation,
    ) -> str:
        if isinstance(parent.node, MappingNode):
            start, end = cls._mapping_entry_range(source, parent, target)
        elif isinstance(parent.node, SequenceNode):
            start, end = cls._sequence_entry_range(source, parent, target)
        else:
            raise TypeError(f"YAML pointer cannot remove a child of {type(parent.value).__name__}")

        if parent.node.flow_style:
            start, end = cls._flow_removal_range(source, parent, target, start, end)
            return cls._splice_source(source, [(start, end, "")])
        if len(parent.node.value) > 1:
            return cls._splice_source(source, [(start, end, "")])
        return cls._empty_block_collection(source, parent, start, end)

    @classmethod
    def _empty_block_collection(
        cls,
        source: str,
        container: _YamlLocation,
        start: int,
        end: int,
    ) -> str:
        marker = "{}" if isinstance(container.node, MappingNode) else "[]"
        if container.parent is None:
            return cls._splice_source(source, [(start, end, marker + "\n")])
        if isinstance(container.parent.node, MappingNode):
            assert container.key_node is not None
            value_indicator = next(
                (
                    token
                    for token in cls._yaml().scan(source)
                    if isinstance(token, ValueToken)
                    and token.start_mark.index >= container.key_node.end_mark.index
                    and token.end_mark.index <= container.node.start_mark.index
                ),
                None,
            )
            if value_indicator is None:
                raise ValueError("could not locate YAML mapping value indicator")
            return cls._splice_source(
                source,
                [
                    (start, end, ""),
                    (
                        value_indicator.end_mark.index,
                        value_indicator.end_mark.index,
                        " " + marker,
                    ),
                ],
            )
        return cls._splice_source(source, [(start, end, marker)])

    @classmethod
    def _mapping_entry_range(
        cls,
        source: str,
        parent: _YamlLocation,
        target: _YamlLocation,
    ) -> tuple[int, int]:
        assert target.key_node is not None
        if parent.node.flow_style:
            value_end = (
                target.alias_token.end_mark.index
                if target.alias_token is not None
                else target.node.end_mark.index
            )
            return target.key_node.start_mark.index, value_end
        line_start = cls._line_start(source, target.key_node.start_mark.index)
        prefix = source[line_start : target.key_node.start_mark.index]
        start = line_start if not prefix.strip() else target.key_node.start_mark.index
        content_end = (
            target.alias_token.end_mark.index
            if target.alias_token is not None
            else cls._node_content_end(target.node)
        )
        end = cls._line_end(source, content_end - 1)
        return start, end

    @classmethod
    def _sequence_entry_range(
        cls,
        source: str,
        parent: _YamlLocation,
        target: _YamlLocation,
    ) -> tuple[int, int]:
        if parent.node.flow_style:
            if target.alias_token is not None:
                return target.alias_token.start_mark.index, target.alias_token.end_mark.index
            return target.node.start_mark.index, target.node.end_mark.index
        assert target.index is not None
        entries = cls._block_sequence_entries(source, parent.node)
        start = cls._line_start(source, entries[target.index].start_mark.index)
        content_end = (
            target.alias_token.end_mark.index
            if target.alias_token is not None
            else cls._node_content_end(target.node)
        )
        end = cls._line_end(source, content_end - 1)
        return start, end

    @staticmethod
    def _flow_removal_range(
        source: str,
        parent: _YamlLocation,
        target: _YamlLocation,
        start: int,
        end: int,
    ) -> tuple[int, int]:
        assert target.index is not None
        count = len(parent.node.value)
        if count == 1:
            _, content_end, separators = (
                BundleDocument._flow_mapping_tokens(source, parent.node)
                if isinstance(parent.node, MappingNode)
                else BundleDocument._flow_sequence_tokens(source, parent.node)
            )
            if separators:
                end = separators[0].end_mark.index
                while end < len(source) and source[end] in " \t":
                    end += 1
            else:
                end = content_end
            return start, end
        if isinstance(parent.node, SequenceNode):
            _, content_end, separators = BundleDocument._flow_sequence_tokens(
                source,
                parent.node,
            )
            if target.index < count - 1:
                end = separators[target.index].end_mark.index
                while end < len(source) and source[end] in " \t":
                    end += 1
                return start, end
            if len(separators) < count:
                end = content_end
            return separators[target.index - 1].start_mark.index, end
        assert isinstance(parent.node, MappingNode)
        _, content_end, separators = BundleDocument._flow_mapping_tokens(
            source,
            parent.node,
        )
        if target.index < count - 1:
            end = separators[target.index].end_mark.index
            while end < len(source) and source[end] in " \t":
                end += 1
            return start, end

        if len(separators) == count:
            end = separators[target.index].end_mark.index
            while end < len(source) and source[end] in " \t":
                end += 1
        else:
            end = content_end
        return separators[target.index - 1].start_mark.index, end

    @classmethod
    def _sequence_entry_bounds(
        cls,
        source: str,
        sequence: SequenceNode,
        index: int,
    ) -> tuple[int, int]:
        if sequence.flow_style:
            content_start, content_end, separators = cls._flow_sequence_tokens(source, sequence)
            start = content_start if index == 0 else separators[index - 1].end_mark.index
            end = (
                content_end
                if index == len(sequence.value) - 1
                else separators[index].start_mark.index
            )
            return start, end
        entries = cls._block_sequence_entries(source, sequence)
        start = entries[index].end_mark.index
        end = (
            entries[index + 1].start_mark.index
            if index + 1 < len(entries)
            else sequence.end_mark.index
        )
        return start, end

    @classmethod
    def _block_sequence_entries(
        cls,
        source: str,
        sequence: SequenceNode,
    ) -> list[BlockEntryToken]:
        return [
            token
            for token in cls._yaml().scan(source)
            if isinstance(token, BlockEntryToken)
            and token.start_mark.column == sequence.start_mark.column
            and sequence.start_mark.index <= token.start_mark.index < sequence.end_mark.index
        ]

    @classmethod
    def _flow_sequence_tokens(
        cls,
        source: str,
        sequence: SequenceNode,
    ) -> tuple[int, int, list[FlowEntryToken]]:
        depth = 0
        content_start = None
        separators: list[FlowEntryToken] = []
        for token in cls._yaml().scan(source):
            if content_start is None:
                if (
                    isinstance(token, FlowSequenceStartToken)
                    and token.start_mark.index == sequence.start_mark.index
                ):
                    content_start = token.end_mark.index
                    depth = 1
                continue
            if isinstance(token, FlowSequenceStartToken | FlowMappingStartToken):
                depth += 1
            elif isinstance(token, FlowSequenceEndToken | FlowMappingEndToken):
                if depth == 1:
                    if not isinstance(token, FlowSequenceEndToken):
                        raise ValueError("could not locate YAML flow sequence end")
                    return content_start, token.start_mark.index, separators
                depth -= 1
            elif isinstance(token, FlowEntryToken) and depth == 1:
                separators.append(token)
        raise ValueError("could not locate YAML flow sequence tokens")

    @classmethod
    def _flow_mapping_tokens(
        cls,
        source: str,
        mapping: MappingNode,
    ) -> tuple[int, int, list[FlowEntryToken]]:
        depth = 0
        content_start = None
        separators: list[FlowEntryToken] = []
        for token in cls._yaml().scan(source):
            if content_start is None:
                if (
                    isinstance(token, FlowMappingStartToken)
                    and token.start_mark.index == mapping.start_mark.index
                ):
                    content_start = token.end_mark.index
                    depth = 1
                continue
            if isinstance(token, FlowSequenceStartToken | FlowMappingStartToken):
                depth += 1
            elif isinstance(token, FlowSequenceEndToken | FlowMappingEndToken):
                if depth == 1:
                    if not isinstance(token, FlowMappingEndToken):
                        raise ValueError("could not locate YAML flow mapping end")
                    return content_start, token.start_mark.index, separators
                depth -= 1
            elif isinstance(token, FlowEntryToken) and depth == 1:
                separators.append(token)
        raise ValueError("could not locate YAML flow mapping tokens")

    @classmethod
    def _first_block_sequence_insertion(
        cls,
        source: str,
        sequence: _YamlLocation,
    ) -> int:
        assert isinstance(sequence.node, SequenceNode)
        if not sequence.node.value:
            return sequence.node.start_mark.index
        entries = cls._block_sequence_entries(source, sequence.node)
        insertion = cls._line_start(source, entries[0].start_mark.index)
        token = next(
            (
                token
                for token in cls._yaml().scan(source)
                if isinstance(token, BlockSequenceStartToken)
                and token.start_mark.index == sequence.node.start_mark.index
            ),
            None,
        )
        comments = getattr(token, "comment", None)
        pre_comments = comments[1] if comments and len(comments) > 1 else None
        if sequence.parent is not None:
            if pre_comments:
                insertion = cls._line_start(source, pre_comments[0].start_mark.index)
            return insertion

        document_start = next(
            (
                candidate
                for candidate in reversed(list(cls._yaml().scan(source)))
                if isinstance(candidate, DocumentStartToken)
                and candidate.start_mark.index < entries[0].start_mark.index
            ),
            None,
        )
        if document_start is not None:
            return cls._line_end(source, document_start.end_mark.index)
        if not pre_comments:
            return insertion

        comment_start = cls._line_start(source, pre_comments[0].start_mark.index)
        prefix = source[comment_start:insertion]
        blank_line = None
        for match in re.finditer(r"(?m)^[ \t]*\r?\n", prefix):
            blank_line = match
        if blank_line is not None:
            return comment_start + blank_line.end()
        return comment_start

    @classmethod
    def _token_pre_comment_start(cls, source: str, token_start: int) -> int:
        for token in cls._yaml().scan(source):
            if token.start_mark.index != token_start:
                continue
            comments = getattr(token, "comment", None)
            pre_comments = comments[1] if comments and len(comments) > 1 else None
            if pre_comments:
                return pre_comments[0].start_mark.index
        return token_start

    @classmethod
    def _flow_end_insertion(
        cls,
        source: str,
        parent: _YamlLocation,
    ) -> tuple[int, bool]:
        end_type = (
            FlowMappingEndToken if isinstance(parent.node, MappingNode) else FlowSequenceEndToken
        )
        for token in cls._yaml().scan(source):
            if (
                not isinstance(token, end_type)
                or token.end_mark.index != parent.node.end_mark.index
            ):
                continue
            comments = getattr(token, "comment", None)
            pre_comments = comments[1] if comments and len(comments) > 1 else None
            if pre_comments:
                return pre_comments[0].start_mark.index, True
            return token.start_mark.index, False
        raise ValueError("could not locate YAML flow collection end")

    @staticmethod
    def _preceding_non_whitespace(source: str, insertion: int) -> str:
        index = insertion - 1
        while index >= 0 and source[index].isspace():
            index -= 1
        return source[index] if index >= 0 else ""

    @classmethod
    def _block_insertion_fragment(
        cls,
        source: str,
        insertion: int,
        fragment: str,
    ) -> str:
        newline = cls._newline_style(source, insertion)
        fragment = fragment.replace("\n", newline)
        if insertion > 0 and source[insertion - 1] not in "\r\n":
            fragment = newline + fragment
        return fragment

    @classmethod
    def _deep_child_footer_end(
        cls,
        source: str,
        insertion: int,
        parent_indent: int,
    ) -> int:
        while insertion < len(source):
            line_end = cls._line_end(source, insertion)
            line = source[insertion:line_end].rstrip("\r\n")
            content = line.lstrip(" \t")
            indent = len(line) - len(content)
            if not content:
                next_line = line_end
                while next_line < len(source):
                    line_end = cls._line_end(source, next_line)
                    line = source[next_line:line_end].rstrip("\r\n")
                    content = line.lstrip(" \t")
                    indent = len(line) - len(content)
                    if content:
                        break
                    next_line = line_end
                if next_line >= len(source):
                    break
            if not content.startswith("#") or indent <= parent_indent:
                break
            insertion = line_end
        return insertion

    @staticmethod
    def _newline_style(source: str, insertion: int) -> str:
        previous = source.rfind("\n", 0, insertion)
        following = source.find("\n", insertion)
        if previous < 0:
            newline = following
        elif following < 0 or insertion - previous <= following - insertion:
            newline = previous
        else:
            newline = following
        if newline > 0 and source[newline - 1] == "\r":
            return "\r\n"
        return "\n"

    @classmethod
    def _render_value_fragment(cls, value: object, *, flow: bool) -> str:
        stream = io.StringIO()
        cls._dump_yaml(flow=flow).dump(value, stream)
        return cls._strip_document_suffix(stream.getvalue())

    @classmethod
    def _render_mapping_entry(
        cls,
        component: str | int,
        value: object,
        *,
        flow: bool,
    ) -> str:
        stream = io.StringIO()
        cls._dump_yaml(flow=flow).dump({component: value}, stream)
        rendered = cls._strip_document_suffix(stream.getvalue())
        return rendered[1:-1] if flow else rendered

    @classmethod
    def _render_sequence_item(cls, value: object, *, flow: bool) -> str:
        stream = io.StringIO()
        yaml = cls._dump_yaml(flow=flow if flow else False)
        if not flow:
            yaml.indent(mapping=2, sequence=2, offset=0)
        yaml.dump([value], stream)
        rendered = cls._strip_document_suffix(stream.getvalue())
        return rendered[1:-1] if flow else rendered

    @staticmethod
    def _strip_document_suffix(rendered: str) -> str:
        if rendered.endswith("\n...\n"):
            rendered = rendered[:-5]
        return rendered.removesuffix("\n")

    @staticmethod
    def _indent_fragment(fragment: str, indent: int) -> str:
        prefix = " " * indent
        return "\n".join(prefix + line if line else line for line in fragment.split("\n"))

    @staticmethod
    def _indent_fragment_continuation(fragment: str, indent: int) -> str:
        lines = fragment.split("\n")
        if len(lines) == 1:
            return fragment
        prefix = " " * indent
        return lines[0] + "\n" + "\n".join(prefix + line if line else line for line in lines[1:])

    @classmethod
    def _node_content_end(cls, node: Node) -> int:
        if isinstance(node, MappingNode) and node.value:
            if node.flow_style:
                return node.end_mark.index
            return cls._node_content_end(node.value[-1][1])
        if isinstance(node, SequenceNode) and node.value:
            if node.flow_style:
                return node.end_mark.index
            return cls._node_content_end(node.value[-1])
        return node.end_mark.index

    @staticmethod
    def _line_start(source: str, index: int) -> int:
        return source.rfind("\n", 0, index) + 1

    @staticmethod
    def _line_end(source: str, index: int) -> int:
        newline = source.find("\n", index)
        return len(source) if newline < 0 else newline + 1

    @staticmethod
    def _splice_source(source: str, edits: Sequence[tuple[int, int, str]]) -> str:
        rendered = source
        previous_start = len(source) + 1
        for start, end, replacement in sorted(edits, reverse=True):
            if not 0 <= start <= end <= len(source) or end > previous_start:
                raise ValueError("invalid or overlapping YAML source edits")
            rendered = rendered[:start] + replacement + rendered[end:]
            previous_start = start
        return rendered

    @staticmethod
    def _child(value: Any, component: str | int) -> Any:
        if isinstance(value, Mapping):
            return value[component]
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            return value[BundleDocument._sequence_index(value, component)]
        raise TypeError(f"YAML pointer cannot traverse {type(value).__name__}")

    @staticmethod
    def _sequence_index(sequence: Sequence[Any], component: str | int) -> int:
        index = int(component)
        if not 0 <= index < len(sequence):
            raise IndexError(f"YAML sequence index out of range: {index}")
        return index

    @staticmethod
    def _sequence_add_index(sequence: Sequence[Any], component: str | int) -> int:
        index = int(component)
        if not 0 <= index <= len(sequence):
            raise IndexError(f"YAML sequence insertion index out of range: {index}")
        return index
