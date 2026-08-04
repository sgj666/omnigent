"""Lossless and safe bundle document behavior."""

from __future__ import annotations

import io
import tarfile
from collections.abc import Mapping

import pytest
from ruamel.yaml.representer import RepresenterError

from omnigent.agent_bundles import BundleDocument
from omnigent.agent_bundles import document as document_module
from omnigent.spec.tar_utils import DEFAULT_MAX_ENTRIES, ExtractionError


def _make_bundle(files: Mapping[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            member = tarfile.TarInfo(path)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


def _make_members(
    members: list[tuple[tarfile.TarInfo, bytes | None]],
    *,
    format: int = tarfile.PAX_FORMAT,
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=format) as archive:
        for member, content in members:
            archive.addfile(member, io.BytesIO(content) if content is not None else None)
    return buffer.getvalue()


def _bundle_files(bundle: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as archive:
        return {
            member.name: extracted.read()
            for member in archive.getmembers()
            if member.isfile() and (extracted := archive.extractfile(member)) is not None
        }


def _file(path: str, content: bytes = b"value") -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(path)
    member.size = len(content)
    return member, content


def _directory(path: str) -> tuple[tarfile.TarInfo, None]:
    member = tarfile.TarInfo(path)
    member.type = tarfile.DIRTYPE
    return member, None


def test_untouched_files_and_yaml_formatting_survive_round_trip() -> None:
    original = _make_bundle(
        {
            "config.yaml": (
                "# coordinator\n"
                "spec_version: 1\n"
                'name: "polly" # display name\n'
                "custom_future: keep\n"
            ),
            "skills/fanout/SKILL.md": "# fanout\n",
            "assets/logo.bin": b"\x00\xff\x10",
        }
    )

    document = BundleDocument.from_bytes(original)
    assert document.exists("skills/fanout/SKILL.md")
    assert document.yaml_value("config.yaml", ("name",)) == "polly"
    document.replace_yaml_value("config.yaml", ("name",), "my-polly")
    reopened = BundleDocument.from_bytes(document.to_bytes())

    config = reopened.read_text("config.yaml")
    assert "# coordinator" in config
    assert 'name: "my-polly" # display name' in config
    assert "custom_future: keep" in config
    assert reopened.read_text("skills/fanout/SKILL.md") == "# fanout\n"
    assert _bundle_files(document.to_bytes())["assets/logo.bin"] == b"\x00\xff\x10"
    assert reopened.to_bytes() == document.to_bytes()


def test_clone_is_independent_and_swap_replaces_the_document() -> None:
    original = BundleDocument.from_bytes(
        _make_bundle({"config.yaml": "name: original\n", "note.txt": "keep\n"})
    )
    edited = original.clone()
    edited.replace_yaml_value("config.yaml", ("name",), "edited")

    assert original.yaml_value("config.yaml", ("name",)) == "original"
    original.swap(edited)
    assert original.yaml_value("config.yaml", ("name",)) == "edited"
    assert original.read_text("note.txt") == "keep\n"


def test_init_normalizes_posix_file_paths() -> None:
    document = BundleDocument({"./a": b"root", "nested//file": b"nested"})

    assert document.read_text("a") == "root"
    assert document.read_text("nested/file") == "nested"
    assert _bundle_files(document.to_bytes()) == {"a": b"root", "nested/file": b"nested"}


@pytest.mark.parametrize(
    "files",
    [
        {"./a": b"first", "a": b"second"},
        {"nested//file": b"first", "nested/file": b"second"},
    ],
)
def test_init_rejects_normalized_path_conflicts(files: dict[str, bytes]) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        BundleDocument(files)


@pytest.mark.parametrize(
    "files",
    [
        {"shared": b"file", "shared/child": b"child"},
        {"shared/child": b"child", "shared": b"file"},
    ],
)
def test_init_rejects_file_namespace_conflicts(files: dict[str, bytes]) -> None:
    with pytest.raises(ValueError, match="conflicting"):
        BundleDocument(files)


@pytest.mark.parametrize(
    "files",
    [
        {"\x00": b"value"},
        {"a\x00hidden": b"hidden"},
        {"a\x00hidden": b"hidden", "a": b"visible"},
    ],
)
def test_init_rejects_nul_paths(files: dict[str, bytes]) -> None:
    with pytest.raises(ValueError, match="NUL"):
        BundleDocument(files)


def test_init_rejects_dangerous_paths() -> None:
    with pytest.raises(ValueError):
        BundleDocument({"../escape": b"value"})


def test_init_rejects_non_utf8_paths() -> None:
    with pytest.raises(ValueError, match="UTF-8"):
        BundleDocument({"bad\udcff": b"value"})


@pytest.mark.parametrize("path", ["../escape", "nested/../../escape", "/absolute"])
def test_from_bytes_rejects_dangerous_paths(path: str) -> None:
    with pytest.raises(ExtractionError):
        BundleDocument.from_bytes(_make_members([_file(path)]))


def test_from_bytes_rejects_duplicate_archive_paths() -> None:
    with pytest.raises(ExtractionError, match="duplicate"):
        BundleDocument.from_bytes(
            _make_members([_file("config.yaml", b"first"), _file("config.yaml", b"second")])
        )


@pytest.mark.parametrize(
    "members",
    [
        [_directory("shared"), _file("shared")],
        [_file("shared"), _directory("shared")],
    ],
)
def test_from_bytes_rejects_file_directory_conflicts_before_extraction(
    members: list[tuple[tarfile.TarInfo, bytes | None]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_if_extracted(*args: object, **kwargs: object) -> None:
        pytest.fail("archive extraction started before preflight completed")

    monkeypatch.setattr(document_module, "extract_safe", fail_if_extracted)

    with pytest.raises(ExtractionError, match="conflicting"):
        BundleDocument.from_bytes(_make_members(members))


def test_from_bytes_rejects_file_before_descendant_before_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_extracted(*args: object, **kwargs: object) -> None:
        pytest.fail("archive extraction started before preflight completed")

    monkeypatch.setattr(document_module, "extract_safe", fail_if_extracted)

    with pytest.raises(ExtractionError, match="conflicting"):
        BundleDocument.from_bytes(_make_members([_file("shared"), _file("shared/child")]))


def test_from_bytes_rejects_descendant_before_file_before_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_extracted(*args: object, **kwargs: object) -> None:
        pytest.fail("archive extraction started before preflight completed")

    monkeypatch.setattr(document_module, "extract_safe", fail_if_extracted)

    with pytest.raises(ExtractionError, match="conflicting"):
        BundleDocument.from_bytes(_make_members([_file("shared/child"), _file("shared")]))


def test_from_bytes_allows_explicit_directory_with_descendant_file() -> None:
    document = BundleDocument.from_bytes(
        _make_members([_directory("shared"), _file("shared/child")])
    )

    assert not document.exists("shared")
    assert document.read_text("shared/child") == "value"


@pytest.mark.parametrize(
    "path",
    [
        "nested\\config.yaml",
        "..\\escape",
        "C:/escape",
        "C:\\escape",
    ],
)
def test_from_bytes_rejects_non_posix_archive_paths(path: str) -> None:
    with pytest.raises(ExtractionError):
        BundleDocument.from_bytes(_make_members([_file(path)]))


def test_from_bytes_rejects_mixed_separator_path_aliases() -> None:
    with pytest.raises(ExtractionError):
        BundleDocument.from_bytes(_make_members([_file("a\\b"), _file("a/b")]))


@pytest.mark.parametrize(
    "members",
    [
        [_file("\x00")],
        [_file("a\x00hidden"), _file("a")],
        [_file(f"{'a' * 101}\x00hidden")],
    ],
    ids=["empty-after-truncation", "truncated-alias", "pax-path"],
)
def test_from_bytes_rejects_nul_paths_before_extraction(
    members: list[tuple[tarfile.TarInfo, bytes | None]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_extracted(*args: object, **kwargs: object) -> None:
        pytest.fail("archive extraction started before preflight completed")

    monkeypatch.setattr(document_module, "extract_safe", fail_if_extracted)

    with pytest.raises(ExtractionError):
        BundleDocument.from_bytes(_make_members(members))


@pytest.mark.parametrize(
    ("format", "path"),
    [
        (tarfile.USTAR_FORMAT, "a\x00hidden"),
        (tarfile.GNU_FORMAT, f"{'g' * 101}\x00hidden"),
    ],
    ids=["ustar-header", "gnu-longlink"],
)
def test_from_bytes_rejects_raw_nul_suffix_before_tarfile_truncation(
    format: int,
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_extracted(*args: object, **kwargs: object) -> None:
        pytest.fail("archive extraction started before raw path preflight completed")

    monkeypatch.setattr(document_module, "extract_safe", fail_if_extracted)

    with pytest.raises(ExtractionError, match="NUL"):
        BundleDocument.from_bytes(_make_members([_file(path)], format=format))


@pytest.mark.parametrize(
    ("format", "path"),
    [
        (tarfile.USTAR_FORMAT, f"{'prefix' * 15}/{'name' * 20}"),
        (tarfile.GNU_FORMAT, "g" * 101),
        (tarfile.PAX_FORMAT, "p" * 101),
    ],
    ids=["ustar-prefix", "gnu-longlink", "pax-path"],
)
def test_from_bytes_allows_valid_extended_tar_paths(format: int, path: str) -> None:
    document = BundleDocument.from_bytes(_make_members([_file(path)], format=format))

    assert document.read_text(path) == "value"


def test_from_bytes_applies_entry_limit_during_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_extracted(*args: object, **kwargs: object) -> None:
        pytest.fail("archive extraction started before preflight completed")

    monkeypatch.setattr(document_module, "extract_safe", fail_if_extracted)
    members = [_file(f"files/{index}", b"") for index in range(DEFAULT_MAX_ENTRIES + 1)]

    with pytest.raises(ExtractionError, match="max entry count"):
        BundleDocument.from_bytes(_make_members(members))


def test_from_bytes_applies_size_limit_during_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_extracted(*args: object, **kwargs: object) -> None:
        pytest.fail("archive extraction started before preflight completed")

    monkeypatch.setattr(document_module, "DEFAULT_MAX_BYTES", 4)
    monkeypatch.setattr(document_module, "extract_safe", fail_if_extracted)

    with pytest.raises(ExtractionError, match="max extracted size"):
        BundleDocument.from_bytes(_make_members([_file("first", b"123"), _file("second", b"45")]))


def test_from_bytes_rejects_non_utf8_path_before_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_extracted(*args: object, **kwargs: object) -> None:
        pytest.fail("archive extraction started before preflight completed")

    monkeypatch.setattr(document_module, "extract_safe", fail_if_extracted)

    with pytest.raises(ExtractionError, match="UTF-8"):
        BundleDocument.from_bytes(_make_members([_file("bad\udcff")]))


@pytest.mark.parametrize("entry_type", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_from_bytes_rejects_non_file_archive_members(entry_type: bytes) -> None:
    member = tarfile.TarInfo("config.yaml")
    member.type = entry_type
    if entry_type in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
        member.linkname = "elsewhere"

    with pytest.raises(ExtractionError):
        BundleDocument.from_bytes(_make_members([(member, None)]))


@pytest.mark.parametrize(
    "pointer,error_type",
    [
        (("settings", "missing"), KeyError),
        (("workers", 2), IndexError),
        (("workers", -1), IndexError),
    ],
)
def test_replace_yaml_value_rejects_missing_or_invalid_targets_without_changes(
    pointer: tuple[str | int, ...], error_type: type[Exception]
) -> None:
    document = BundleDocument.from_bytes(
        _make_bundle(
            {"config.yaml": ("settings:\n  name: original\nworkers:\n  - first\n  - second\n")}
        )
    )
    before = document.to_bytes()

    with pytest.raises(error_type):
        document.replace_yaml_value("config.yaml", pointer, "replacement")

    assert document.to_bytes() == before


@pytest.mark.parametrize("pointer", [(), ("settings", "name")])
def test_replace_yaml_value_is_atomic_when_rendering_fails(
    pointer: tuple[str | int, ...],
) -> None:
    document = BundleDocument.from_bytes(
        _make_bundle({"config.yaml": "settings:\n  name: original\n"})
    )
    before_text = document.read_text("config.yaml")
    before_value = document.yaml_value("config.yaml", ())
    before_bundle = document.to_bytes()

    with pytest.raises(RepresenterError):
        document.replace_yaml_value("config.yaml", pointer, object())

    assert document.read_text("config.yaml") == before_text
    assert document.yaml_value("config.yaml", ()) == before_value
    assert document.to_bytes() == before_bundle


def test_to_bytes_revalidates_internal_file_paths() -> None:
    document = BundleDocument({"safe": b"value"})
    document._files["../escape"] = b"unsafe"

    with pytest.raises(ValueError):
        document.to_bytes()


@pytest.mark.parametrize(
    "files",
    [
        {"shared": b"file", "shared/child": b"child"},
        {"shared/child": b"child", "shared": b"file"},
    ],
)
def test_to_bytes_rejects_file_namespace_conflicts(files: dict[str, bytes]) -> None:
    document = BundleDocument({"safe": b"value"})
    document._files = files

    with pytest.raises(ValueError, match="conflicting"):
        document.to_bytes()


def test_to_bytes_is_deterministic_and_normalizes_tar_metadata() -> None:
    document = BundleDocument.from_bytes(
        _make_bundle({"z.txt": b"z", "config.yaml": "name: agent\n", "a.txt": b"a"})
    )

    first = document.to_bytes()
    second = document.to_bytes()
    assert first == second
    assert int.from_bytes(first[4:8], "little") == 0
    assert first[3] & 0x08 == 0

    with tarfile.open(fileobj=io.BytesIO(first), mode="r:gz") as archive:
        members = archive.getmembers()
    assert [member.name for member in members] == ["a.txt", "config.yaml", "z.txt"]
    assert all(member.isfile() for member in members)
    assert all(member.mode == 0o644 for member in members)
    assert all(
        (member.uid, member.gid, member.uname, member.gname, member.mtime) == (0, 0, "", "", 0)
        for member in members
    )
