"""Typed edits for Agent Template bundle files."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from omnigent.agent_bundles.document import BundleDocument, YamlPointer


class _MissingValue:
    pass


MISSING: Final = _MissingValue()

BundlePatchOperation = Literal["add", "replace", "remove", "replace_file", "delete_file"]
_PATCH_ERROR_MESSAGE = "patch could not be applied"


@dataclass(frozen=True)
class BundlePatch:
    """One requested edit to a file in a bundle."""

    file: str
    op: BundlePatchOperation
    path: str = ""
    value: object = MISSING


class BundlePatchError(ValueError):
    """A content-safe failure while applying one bundle patch."""

    def __init__(self, file: str, path: str, message: str) -> None:
        self.file = file
        self.path = path
        self.message = message
        super().__init__(f"bundle patch failed for {file!r} at {path!r}: {message}")


class _PatchFailure(Exception):
    pass


def apply_patches(document: BundleDocument, patches: Iterable[BundlePatch]) -> None:
    """Apply *patches* in order, swapping the result only after all succeed."""
    file = ""
    path = ""
    try:
        candidate = document.clone()
        for patch in patches:
            file = patch.file
            path = patch.path
            _apply_patch(candidate, patch)
        document.swap(candidate)
    except Exception:  # noqa: BLE001 - public boundary must sanitize patch failures
        raise BundlePatchError(file, path, _PATCH_ERROR_MESSAGE) from None


def _apply_patch(document: BundleDocument, patch: BundlePatch) -> None:
    if not isinstance(patch.file, str):
        raise _PatchFailure("invalid bundle file path")
    try:
        exists = document.exists(patch.file)
    except (TypeError, ValueError, UnicodeError):
        raise _PatchFailure("invalid bundle file path") from None
    if not exists:
        raise _PatchFailure("file does not exist")

    if patch.op == "replace_file":
        _require_file_operation_path(patch)
        if not isinstance(patch.value, str):
            raise _PatchFailure("replace_file value must be a UTF-8 string")
        try:
            rendered = patch.value.encode("utf-8")
        except UnicodeEncodeError:
            raise _PatchFailure("replace_file value must be a UTF-8 string") from None
        document.replace_file_bytes(patch.file, rendered)
        return

    if patch.op == "delete_file":
        _require_file_operation_path(patch)
        document.delete_file(patch.file)
        return

    if patch.op not in {"add", "replace", "remove"}:
        raise _PatchFailure("unsupported patch operation")
    if patch.op in {"add", "replace"} and patch.value is MISSING:
        raise _PatchFailure("value is required for this operation")

    tokens = _decode_json_pointer(patch.path)
    pointer = _resolve_yaml_pointer(document, patch.file, tokens, patch.op)
    if patch.op == "add":
        document.add_yaml_value(patch.file, pointer, patch.value)
    elif patch.op == "replace":
        document.replace_yaml_value(patch.file, pointer, patch.value)
    else:
        document.remove_yaml_value(patch.file, pointer)


def _require_file_operation_path(patch: BundlePatch) -> None:
    if patch.path != "":
        raise _PatchFailure("file operations require an empty JSON pointer")


def _decode_json_pointer(path: str) -> tuple[str, ...]:
    if not isinstance(path, str) or (path and not path.startswith("/")):
        raise _PatchFailure("invalid JSON pointer")
    if not path:
        return ()

    decoded: list[str] = []
    for token in path[1:].split("/"):
        index = 0
        while index < len(token):
            if token[index] == "~":
                if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
                    raise _PatchFailure("invalid JSON pointer escape")
                index += 2
            else:
                index += 1
        decoded.append(token.replace("~1", "/").replace("~0", "~"))
    return tuple(decoded)


def _resolve_yaml_pointer(
    document: BundleDocument,
    file: str,
    tokens: Sequence[str],
    operation: Literal["add", "replace", "remove"],
) -> YamlPointer:
    value = document.yaml_value(file, ())
    resolved: list[str | int] = []
    for position, token in enumerate(tokens):
        final = position == len(tokens) - 1
        if isinstance(value, Mapping):
            resolved.append(token)
            if not final:
                if token not in value:
                    raise _PatchFailure("target does not exist")
                value = value[token]
            continue
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            if token == "-" and final and operation == "add":
                resolved.append(token)
                continue
            index = _array_index(token)
            upper_bound = len(value) if final and operation == "add" else len(value) - 1
            if not 0 <= index <= upper_bound:
                raise _PatchFailure("array index is out of range")
            resolved.append(index)
            if not final:
                value = value[index]
            continue
        raise _PatchFailure("target cannot contain the requested child")
    return tuple(resolved)


def _array_index(token: str) -> int:
    if token == "0":
        return 0
    if not token or token[0] == "0" or not token.isascii() or not token.isdecimal():
        raise _PatchFailure("invalid array index")
    return int(token)
