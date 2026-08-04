"""Safe, lossless editing of gzipped Agent Template bundles."""

from __future__ import annotations

import copy
import gzip
import io
import re
import tarfile
import tempfile
from collections.abc import Mapping, MutableMapping, MutableSequence, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Self

from ruamel.yaml import YAML

from omnigent.spec.tar_utils import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_ENTRIES,
    ExtractionError,
    extract_safe,
)

YamlPointer = Sequence[str | int]


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
        document = self._yaml_document(normalized)
        if not pointer:
            candidate = copy.deepcopy(value)
        else:
            candidate = copy.deepcopy(document)
            parent = candidate
            for component in pointer[:-1]:
                parent = self._child(parent, component)
            self._replace_child(parent, pointer[-1], copy.deepcopy(value))

        stream = io.StringIO()
        self._yaml().dump(candidate, stream)
        rendered = stream.getvalue().encode("utf-8")
        self._yaml_documents[normalized] = candidate
        self._files[normalized] = rendered

    def clone(self) -> BundleDocument:
        """Return a fully independent copy suitable for atomic edits."""
        clone = BundleDocument(self._files)
        clone._yaml_documents = copy.deepcopy(self._yaml_documents)
        return clone

    def swap(self, other: BundleDocument) -> None:
        """Replace this document with an independent snapshot of *other*."""
        self._files = dict(other._files)
        self._yaml_documents = copy.deepcopy(other._yaml_documents)

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
            yaml = self._yaml()
            self._yaml_documents[normalized] = yaml.load(self.read_text(normalized))
        return self._yaml_documents[normalized]

    @staticmethod
    def _yaml() -> YAML:
        yaml = YAML(typ="rt")
        yaml.preserve_quotes = True
        return yaml

    @staticmethod
    def _child(value: Any, component: str | int) -> Any:
        if isinstance(value, Mapping):
            return value[component]
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            return value[BundleDocument._sequence_index(value, component)]
        raise TypeError(f"YAML pointer cannot traverse {type(value).__name__}")

    @staticmethod
    def _replace_child(parent: Any, component: str | int, value: object) -> None:
        if isinstance(parent, MutableMapping):
            if component not in parent:
                raise KeyError(component)
            parent[component] = value
            return
        if isinstance(parent, MutableSequence):
            parent[BundleDocument._sequence_index(parent, component)] = value
            return
        raise TypeError(f"YAML pointer cannot replace a child of {type(parent).__name__}")

    @staticmethod
    def _sequence_index(sequence: Sequence[Any], component: str | int) -> int:
        index = int(component)
        if not 0 <= index < len(sequence):
            raise IndexError(f"YAML sequence index out of range: {index}")
        return index
