"""Typed, atomic Agent Template bundle patches."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from omnigent.agent_bundles import BundleDocument
from omnigent.agent_bundles.patches import (
    MISSING,
    BundlePatch,
    BundlePatchError,
    apply_patches,
)

_PATCH_ERROR_MESSAGE = "patch could not be applied"


class _ExplodingDeepcopy:
    def __deepcopy__(self, memo: dict[int, object]) -> object:
        del memo
        raise RuntimeError("sensitive-deepcopy-detail")


class _InterruptingDeepcopy:
    def __deepcopy__(self, memo: dict[int, object]) -> object:
        del memo
        raise KeyboardInterrupt


def _assert_sanitized(error: BundlePatchError) -> None:
    assert error.message == _PATCH_ERROR_MESSAGE


def test_bundle_patch_distinguishes_missing_value_from_explicit_null() -> None:
    missing = BundlePatch(file="config.yaml", op="remove", path="/enabled")
    explicit_null = BundlePatch(file="config.yaml", op="replace", path="/enabled", value=None)

    assert missing.value is MISSING
    assert explicit_null.value is None
    with pytest.raises(FrozenInstanceError):
        missing.path = "/changed"  # type: ignore[misc]


def test_remove_preserves_missing_vs_explicit_false() -> None:
    document = BundleDocument({"config.yaml": b"enabled: false\nname: agent\n"})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path="/enabled")],
    )

    assert document.yaml_value("config.yaml", ()) == {"name": "agent"}


def test_remove_mapping_key_preserves_comment_for_successor() -> None:
    document = BundleDocument(
        {"config.yaml": (b"remove: x # inline for remove\n# docs for keep\nkeep: y\n")}
    )

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path="/remove")],
    )

    rendered = document.read_text("config.yaml")
    assert "# docs for keep" in rendered
    assert "# inline for remove" not in rendered
    assert document.yaml_value("config.yaml", ()) == {"keep": "y"}


def test_remove_sequence_item_preserves_comment_for_successor() -> None:
    document = BundleDocument(
        {"config.yaml": (b"items:\n  - remove # inline for remove\n  # docs for keep\n  - keep\n")}
    )

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path="/items/0")],
    )

    rendered = document.read_text("config.yaml")
    assert "# docs for keep" in rendered
    assert "# inline for remove" not in rendered
    assert document.yaml_value("config.yaml", ("items",)) == ["keep"]


def test_remove_last_mapping_key_preserves_document_footer_comment() -> None:
    document = BundleDocument(
        {"config.yaml": (b"keep: y\nremove: x # inline for remove\n# document footer\n")}
    )

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path="/remove")],
    )

    rendered = document.read_text("config.yaml")
    assert "# document footer" in rendered
    assert "# inline for remove" not in rendered
    assert document.yaml_value("config.yaml", ()) == {"keep": "y"}


def test_remove_last_sequence_item_preserves_document_footer_comment() -> None:
    document = BundleDocument(
        {
            "config.yaml": (
                b"items:\n  - keep\n  - remove # inline for remove\n  # document footer\n"
            )
        }
    )

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path="/items/1")],
    )

    rendered = document.read_text("config.yaml")
    assert "# document footer" in rendered
    assert "# inline for remove" not in rendered
    assert document.yaml_value("config.yaml", ("items",)) == ["keep"]


def test_remove_only_nested_mapping_key_keeps_footer_and_valid_yaml() -> None:
    document = BundleDocument(
        {"config.yaml": (b"outer:\n  remove: x # inline for remove\n  # nested mapping footer\n")}
    )

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path="/outer/remove")],
    )

    assert document.yaml_value("config.yaml", ()) == {"outer": {}}
    rendered = document.read_text("config.yaml")
    assert "# nested mapping footer" in rendered
    assert "# inline for remove" not in rendered


def test_remove_only_nested_sequence_item_keeps_footer_and_valid_yaml() -> None:
    document = BundleDocument(
        {
            "config.yaml": (
                b"outer:\n"
                b"  items:\n"
                b"    - remove # inline for remove\n"
                b"    # nested sequence footer\n"
            )
        }
    )

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path="/outer/items/0")],
    )

    assert document.yaml_value("config.yaml", ()) == {"outer": {"items": []}}
    rendered = document.read_text("config.yaml")
    assert "# nested sequence footer" in rendered
    assert "# inline for remove" not in rendered


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("collection_kind", ["mapping", "sequence"])
def test_remove_only_explicit_key_value_uses_the_real_value_indicator(
    newline: str,
    collection_kind: str,
) -> None:
    comment = '# docs: {"kind": "value", "url": "https://host:a:b"}'
    child = "  child: remove" if collection_kind == "mapping" else "  - remove"
    marker = "{}" if collection_kind == "mapping" else "[]"
    path = "/target key/child" if collection_kind == "mapping" else "/target key/0"
    yaml_text = newline.join(
        [
            f'? "target key" {comment}',
            ":",
            child,
            "root: stay",
            "",
        ]
    )
    expected = newline.join(
        [
            f'? "target key" {comment}',
            f": {marker}",
            "root: stay",
            "",
        ]
    )
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path=path)],
    )

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    expected_value: object = {} if collection_kind == "mapping" else []
    assert document.yaml_value("config.yaml", ()) == {
        "target key": expected_value,
        "root": "stay",
    }
    if newline == "\r\n":
        assert "\n" not in rendered.replace("\r\n", "")


@pytest.mark.parametrize(
    ("yaml_text", "path", "expected"),
    [
        (
            "outer:\n  remove: x # inline for remove\n# document footer\n",
            "/outer/remove",
            {"outer": {}},
        ),
        (
            "outer:\n  items:\n    - remove # inline for remove\n# document footer\n",
            "/outer/items/0",
            {"outer": {"items": []}},
        ),
    ],
    ids=["mapping", "sequence"],
)
def test_remove_only_nested_item_preserves_zero_indent_document_footer(
    yaml_text: str,
    path: str,
    expected: object,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path=path)],
    )
    reopened = BundleDocument.from_bytes(document.to_bytes())

    assert reopened.yaml_value("config.yaml", ()) == expected
    rendered = reopened.read_text("config.yaml")
    assert rendered.count("# document footer") == 1
    assert "# inline for remove" not in rendered


@pytest.mark.parametrize(
    ("yaml_text", "path", "expected", "nested_footer"),
    [
        (
            "outer:\n"
            "  remove: x # inline for remove\n"
            "  # nested mapping footer\n"
            "# document footer\n",
            "/outer/remove",
            {"outer": {}},
            "# nested mapping footer",
        ),
        (
            "outer:\n"
            "  items:\n"
            "    - remove # inline for remove\n"
            "    # nested sequence footer\n"
            "# document footer\n",
            "/outer/items/0",
            {"outer": {"items": []}},
            "# nested sequence footer",
        ),
    ],
    ids=["mapping", "sequence"],
)
def test_remove_only_nested_item_preserves_mixed_indent_footers(
    yaml_text: str,
    path: str,
    expected: object,
    nested_footer: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path=path)],
    )
    reopened = BundleDocument.from_bytes(document.to_bytes())

    assert reopened.yaml_value("config.yaml", ()) == expected
    rendered = reopened.read_text("config.yaml")
    assert rendered.count(nested_footer) == 1
    assert rendered.count("# document footer") == 1
    assert "# inline for remove" not in rendered


@pytest.mark.parametrize(
    ("yaml_text", "path", "expected", "empty_collection"),
    [
        (
            "root:\n"
            "  outer:\n"
            "    remove: x # inline for remove\n"
            "    # inner footer\n"
            "  # outer footer\n"
            "# document footer\n",
            "/root/outer/remove",
            {"root": {"outer": {}}},
            "{}",
        ),
        (
            "root:\n"
            "  outer:\n"
            "    - remove # inline for remove\n"
            "    # inner footer\n"
            "  # outer footer\n"
            "# document footer\n",
            "/root/outer/0",
            {"root": {"outer": []}},
            "[]",
        ),
    ],
    ids=["mapping", "sequence"],
)
def test_remove_only_deeply_nested_item_preserves_each_footer_level(
    yaml_text: str,
    path: str,
    expected: object,
    empty_collection: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path=path)],
    )
    reopened = BundleDocument.from_bytes(document.to_bytes())

    assert reopened.yaml_value("config.yaml", ()) == expected
    rendered = reopened.read_text("config.yaml")
    assert empty_collection in rendered
    assert rendered.count("# inner footer") == 1
    assert rendered.count("# outer footer") == 1
    assert rendered.count("# document footer") == 1
    assert "# inline for remove" not in rendered


@pytest.mark.parametrize(
    ("successor_yaml", "expected_successor"),
    [
        ("    - keep\n", ["keep"]),
        ("    keep: y\n", {"keep": "y"}),
    ],
    ids=["sequence-successor", "mapping-successor"],
)
def test_remove_only_nested_sequence_item_does_not_corrupt_block_successor(
    successor_yaml: str,
    expected_successor: object,
) -> None:
    document = BundleDocument(
        {
            "config.yaml": (
                "root:\n"
                "  first:\n"
                "    - remove # inline for remove\n"
                "    # inner footer\n"
                "  second:\n"
                f"{successor_yaml}"
            ).encode()
        }
    )

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path="/root/first/0")],
    )
    reopened = BundleDocument.from_bytes(document.to_bytes())

    assert reopened.yaml_value("config.yaml", ()) == {
        "root": {"first": [], "second": expected_successor}
    }
    rendered = reopened.read_text("config.yaml")
    assert rendered.count("# inner footer") == 1
    assert rendered.index("first: []") < rendered.index("# inner footer")
    assert rendered.index("# inner footer") < rendered.index("second:")
    assert "# inline for remove" not in rendered


@pytest.mark.parametrize(
    ("first_yaml", "path", "expected_first", "empty_collection"),
    [
        (
            "    remove: x # inline for remove\n    # inner footer\n",
            "/root/first/remove",
            {},
            "{}",
        ),
        (
            "    - remove # inline for remove\n    # inner footer\n",
            "/root/first/0",
            [],
            "[]",
        ),
    ],
    ids=["mapping", "sequence"],
)
def test_remove_preserves_ancestor_successor_comments_before_successor(
    first_yaml: str,
    path: str,
    expected_first: object,
    empty_collection: str,
) -> None:
    document = BundleDocument(
        {
            "config.yaml": (
                f"root:\n  first:\n{first_yaml}  # docs for second\n  second:\n    keep: y\n"
            ).encode()
        }
    )

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path=path)],
    )
    reopened = BundleDocument.from_bytes(document.to_bytes())

    assert reopened.yaml_value("config.yaml", ()) == {
        "root": {"first": expected_first, "second": {"keep": "y"}}
    }
    rendered = reopened.read_text("config.yaml")
    assert rendered.count("# inner footer") == 1
    assert rendered.count("# docs for second") == 1
    assert rendered.index(f"first: {empty_collection}") < rendered.index("# inner footer")
    assert rendered.index("# inner footer") < rendered.index("# docs for second")
    assert rendered.index("# docs for second") < rendered.index("second:")
    assert "# inline for remove" not in rendered


@pytest.mark.parametrize(
    ("item_yaml", "item_path", "empty_collection"),
    [
        ("    remove: x", "remove", "{}"),
        ("    - remove", "0", "[]"),
    ],
    ids=["mapping", "sequence"],
)
def test_batch_remove_preserves_each_ancestor_successor_comment_position(
    item_yaml: str,
    item_path: str,
    empty_collection: str,
) -> None:
    document = BundleDocument(
        {
            "config.yaml": (
                "root:\n"
                "  first:\n"
                f"{item_yaml} # inline for first\n"
                "  # docs for second\n"
                "  second:\n"
                f"{item_yaml} # inline for second\n"
                "  # docs for third\n"
                "  third: keep\n"
            ).encode()
        }
    )

    apply_patches(
        document,
        [
            BundlePatch(
                file="config.yaml",
                op="remove",
                path=f"/root/first/{item_path}",
            ),
            BundlePatch(
                file="config.yaml",
                op="remove",
                path=f"/root/second/{item_path}",
            ),
        ],
    )
    reopened = BundleDocument.from_bytes(document.to_bytes())

    expected_empty: object = {} if empty_collection == "{}" else []
    assert reopened.yaml_value("config.yaml", ()) == {
        "root": {"first": expected_empty, "second": expected_empty, "third": "keep"}
    }
    rendered = reopened.read_text("config.yaml")
    assert rendered.count("# docs for second") == 1
    assert rendered.count("# docs for third") == 1
    assert rendered.index(f"first: {empty_collection}") < rendered.index("# docs for second")
    assert rendered.index("# docs for second") < rendered.index(f"second: {empty_collection}")
    assert rendered.index(f"second: {empty_collection}") < rendered.index("# docs for third")
    assert rendered.index("# docs for third") < rendered.index("third: keep")
    assert "# inline for first" not in rendered
    assert "# inline for second" not in rendered


@pytest.mark.parametrize(
    ("first_yaml", "leaf_path"),
    [
        ("    leaf: remove\n", "leaf"),
        ("    - remove\n", "0"),
    ],
    ids=["nested-mapping-leaf", "nested-sequence-leaf"],
)
@pytest.mark.parametrize(
    "second_yaml",
    ["keep", "{nested: keep}", "[keep]"],
    ids=["scalar-successor", "mapping-successor", "sequence-successor"],
)
def test_three_remove_batch_keeps_successor_comment_on_empty_nested_mapping(
    first_yaml: str,
    leaf_path: str,
    second_yaml: str,
) -> None:
    document = BundleDocument(
        {
            "config.yaml": (
                f"root:\n  first:\n{first_yaml}  # docs second\n  second: {second_yaml}\n"
            ).encode()
        }
    )

    apply_patches(
        document,
        [
            BundlePatch(file="config.yaml", op="remove", path=f"/root/first/{leaf_path}"),
            BundlePatch(file="config.yaml", op="remove", path="/root/first"),
            BundlePatch(file="config.yaml", op="remove", path="/root/second"),
        ],
    )
    reopened = BundleDocument.from_bytes(document.to_bytes())

    assert reopened.yaml_value("config.yaml", ()) == {"root": {}}
    rendered = reopened.read_text("config.yaml")
    assert rendered.count("# docs second") == 1
    assert rendered.index("root:") < rendered.index("# docs second")
    assert "{}" in rendered


def test_four_remove_batch_preserves_successor_comments_in_order() -> None:
    document = BundleDocument(
        {
            "config.yaml": (
                b"root:\n"
                b"  first:\n"
                b"    - remove\n"
                b"  # docs second\n"
                b"  second: remove\n"
                b"  # docs third\n"
                b"  third: remove\n"
            )
        }
    )

    apply_patches(
        document,
        [
            BundlePatch(file="config.yaml", op="remove", path="/root/first/0"),
            BundlePatch(file="config.yaml", op="remove", path="/root/first"),
            BundlePatch(file="config.yaml", op="remove", path="/root/second"),
            BundlePatch(file="config.yaml", op="remove", path="/root/third"),
        ],
    )
    reopened = BundleDocument.from_bytes(document.to_bytes())

    assert reopened.yaml_value("config.yaml", ()) == {"root": {}}
    rendered = reopened.read_text("config.yaml")
    assert rendered.count("# docs second") == 1
    assert rendered.count("# docs third") == 1
    assert rendered.index("# docs second") < rendered.index("# docs third")


@pytest.mark.parametrize(
    "second_yaml",
    ["remove", "{nested: remove}", "[remove]"],
    ids=["scalar-successor", "mapping-successor", "sequence-successor"],
)
def test_batch_remove_middle_and_end_keeps_deleted_successor_pre_comment(
    second_yaml: str,
) -> None:
    document = BundleDocument(
        {
            "config.yaml": (
                "root:\n"
                "  first: {}\n"
                "  # docs second\n"
                f"  second: {second_yaml}\n"
                "  third: remove\n"
            ).encode()
        }
    )

    apply_patches(
        document,
        [
            BundlePatch(file="config.yaml", op="remove", path="/root/second"),
            BundlePatch(file="config.yaml", op="remove", path="/root/third"),
        ],
    )
    reopened = BundleDocument.from_bytes(document.to_bytes())

    assert reopened.yaml_value("config.yaml", ()) == {"root": {"first": {}}}
    rendered = reopened.read_text("config.yaml")
    assert rendered.count("# docs second") == 1
    assert rendered.index("first: {}") < rendered.index("# docs second")


@pytest.mark.parametrize(
    ("yaml_text", "patches", "expected"),
    [
        (
            "first:\n  - remove\n# docs second\nsecond: remove\n",
            [
                BundlePatch(file="config.yaml", op="remove", path="/first/0"),
                BundlePatch(file="config.yaml", op="remove", path="/first"),
                BundlePatch(file="config.yaml", op="remove", path="/second"),
            ],
            {},
        ),
        (
            "- first:\n    - remove\n# docs second\n- remove\n",
            [
                BundlePatch(file="config.yaml", op="remove", path="/0/first/0"),
                BundlePatch(file="config.yaml", op="remove", path="/0"),
                BundlePatch(file="config.yaml", op="remove", path="/0"),
            ],
            [],
        ),
    ],
    ids=["root-mapping", "root-sequence"],
)
def test_three_remove_batch_keeps_comment_when_root_collection_becomes_empty(
    yaml_text: str,
    patches: list[BundlePatch],
    expected: object,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(document, patches)
    reopened = BundleDocument.from_bytes(document.to_bytes())

    assert reopened.yaml_value("config.yaml", ()) == expected
    assert reopened.read_text("config.yaml").count("# docs second") == 1


@pytest.mark.parametrize(
    ("yaml_text", "path", "expected", "successor"),
    [
        (
            "remove: x # inline for remove\n# docs for keep\nkeep: y\n",
            "/remove",
            {"keep": "y"},
            "keep: y",
        ),
        (
            "- remove # inline for remove\n# docs for keep\n- keep\n",
            "/0",
            ["keep"],
            "- keep",
        ),
    ],
    ids=["mapping", "sequence"],
)
def test_remove_preserves_zero_indent_comment_before_successor(
    yaml_text: str,
    path: str,
    expected: object,
    successor: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path=path)],
    )
    reopened = BundleDocument.from_bytes(document.to_bytes())

    assert reopened.yaml_value("config.yaml", ()) == expected
    rendered = reopened.read_text("config.yaml")
    assert rendered.count("# docs for keep") == 1
    assert rendered.index("# docs for keep") < rendered.index(successor)
    assert "# inline for remove" not in rendered


@pytest.mark.parametrize(
    ("yaml_text", "path", "expected", "footer"),
    [
        (
            "remove: x # inline for remove\n# top mapping footer\n",
            "/remove",
            {},
            "# top mapping footer",
        ),
        (
            "- remove # inline for remove\n# top sequence footer\n",
            "/0",
            [],
            "# top sequence footer",
        ),
    ],
    ids=["mapping", "sequence"],
)
def test_remove_only_top_level_item_keeps_footer_and_valid_yaml(
    yaml_text: str,
    path: str,
    expected: object,
    footer: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path=path)],
    )

    assert document.yaml_value("config.yaml", ()) == expected
    rendered = document.read_text("config.yaml")
    assert footer in rendered
    assert "# inline for remove" not in rendered


@pytest.mark.parametrize(
    "yaml_text",
    [
        ("name: old\nitems:\n  - one\n  - two\nroot:\n    deep: value\n"),
        (
            "name: old\n"
            "outer:\n"
            "  items:\n"
            "    - name: one\n"
            "      metadata:\n"
            "        key: value\n"
            "    - name: two\n"
            "  nested:\n"
            "    deep: value\n"
        ),
        ("name: old\nitems:\n- one\n- two\nroot:\n    deep:\n        leaf: value\n"),
    ],
    ids=[
        "mapping-4-sequence-offset-2",
        "mapping-2-nested-sequence-offset-2",
        "mapping-4-sequence-offset-0",
    ],
)
def test_replace_preserves_untouched_mapping_and_sequence_indentation(
    yaml_text: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/name", value="new")],
    )

    assert document.read_text("config.yaml") == yaml_text.replace("name: old", "name: new")


@pytest.mark.parametrize(
    "yaml_text",
    [
        ("name: old\nfirst:\n  child:\n    leaf: one\nsecond:\n    child:\n        leaf: two\n"),
        ("name: old\nfirst:\n  child:\n    - one\nsecond:\n    child:\n        - two\n"),
    ],
    ids=["mixed-mapping-indent", "mixed-mapping-sequence-indent"],
)
def test_replace_preserves_independent_local_subtree_indentation(yaml_text: str) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/name", value="new")],
    )

    assert document.read_text("config.yaml") == yaml_text.replace("name: old", "name: new")


def test_empty_flow_mapping_is_not_used_as_block_indentation_sample() -> None:
    yaml_text = "name: old\nempty: {}\nnested:\n  child: keep\n"
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/name", value="new")],
    )

    assert document.read_text("config.yaml") == yaml_text.replace("name: old", "name: new")


_UNTOUCHED_SPECIAL_SUBTREE = (
    "untouched:\n"
    "    mixed_mapping:\n"
    "        leaf: keep\n"
    "    mixed_sequence:\n"
    "        - keep\n"
    "    flow_value: {a: # KEEP VALUE\n"
    "        [x, y]}\n"
    "    flow_key: {? [a, # KEEP KEY\n"
    "        b]: v}\n"
)


@pytest.mark.parametrize(
    ("patch", "pointer", "expected"),
    [
        (
            BundlePatch(file="config.yaml", op="add", path="/target_map/added", value="new"),
            ("target_map",),
            {"old": "value", "added": "new"},
        ),
        (
            BundlePatch(file="config.yaml", op="replace", path="/target_map/old", value="new"),
            ("target_map",),
            {"old": "new"},
        ),
        (
            BundlePatch(file="config.yaml", op="remove", path="/target_map/old"),
            ("target_map",),
            {},
        ),
        (
            BundlePatch(file="config.yaml", op="add", path="/target_seq/1", value="new"),
            ("target_seq",),
            ["old", "new"],
        ),
        (
            BundlePatch(file="config.yaml", op="replace", path="/target_seq/0", value="new"),
            ("target_seq",),
            ["new"],
        ),
        (
            BundlePatch(file="config.yaml", op="remove", path="/target_seq/0"),
            ("target_seq",),
            [],
        ),
    ],
    ids=[
        "mapping-add",
        "mapping-replace",
        "mapping-remove",
        "sequence-add",
        "sequence-replace",
        "sequence-remove",
    ],
)
def test_structured_ops_preserve_an_untouched_special_subtree_verbatim(
    patch: BundlePatch,
    pointer: tuple[str, ...],
    expected: object,
) -> None:
    yaml_text = (
        "target_map:\n"
        "  old: value\n"
        "target_seq:\n"
        "  - old\n"
        f"{_UNTOUCHED_SPECIAL_SUBTREE}"
        "tail: keep\n"
    )
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(document, [patch])

    assert _UNTOUCHED_SPECIAL_SUBTREE in document.read_text("config.yaml")
    assert document.yaml_value("config.yaml", pointer) == expected


@pytest.mark.parametrize(
    ("yaml_text", "expected_settings"),
    [
        (
            "name: old\nsettings: [a, # keep b docs\n  b]\n",
            ["a", "b"],
        ),
        (
            "name: old\nsettings: {a: 1, # keep b docs\n  b: 2}\n",
            {"a": 1, "b": 2},
        ),
    ],
    ids=["flow-sequence", "flow-mapping"],
)
def test_replace_preserves_untouched_flow_collection_inline_comment(
    yaml_text: str,
    expected_settings: object,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/name", value="new")],
    )

    assert document.read_text("config.yaml") == yaml_text.replace("name: old", "name: new")
    assert document.yaml_value("config.yaml", ("settings",)) == expected_settings


@pytest.mark.parametrize(
    ("yaml_text", "expected_settings"),
    [
        (
            "name: old\nsettings: [ # keep a docs\n  a, b]\n",
            ["a", "b"],
        ),
        (
            "name: old\nsettings: { # keep a docs\n  a: 1, b: 2}\n",
            {"a": 1, "b": 2},
        ),
        (
            "name: old\nouter:\n  settings: [a, # keep b docs\n    b]\n",
            ["a", "b"],
        ),
        (
            "name: old\nouter:\n  settings: {a: 1, # keep b docs\n    b: 2}\n",
            {"a": 1, "b": 2},
        ),
    ],
    ids=[
        "first-flow-sequence-item",
        "first-flow-mapping-key",
        "nested-flow-sequence-successor",
        "nested-flow-mapping-successor",
    ],
)
def test_replace_preserves_first_and_nested_flow_collection_comments(
    yaml_text: str,
    expected_settings: object,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/name", value="new")],
    )

    assert document.read_text("config.yaml") == yaml_text.replace("name: old", "name: new")
    pointer = (
        ("settings",)
        if "settings" in document.yaml_value("config.yaml", ())
        else (
            "outer",
            "settings",
        )
    )
    assert document.yaml_value("config.yaml", pointer) == expected_settings


@pytest.mark.parametrize(
    "flow_value",
    ["value", "[x, y]", "{x: y}"],
    ids=["scalar", "flow-sequence", "flow-mapping"],
)
@pytest.mark.parametrize("nested", [False, True], ids=["first", "nested"])
def test_replace_preserves_flow_mapping_value_pre_comment(
    flow_value: str,
    nested: bool,
) -> None:
    yaml_text = (
        f"name: old\nouter: {{m: {{a: # KEEP\n    {flow_value}}}}}\n"
        if nested
        else f"name: old\nm: {{a: # KEEP\n  {flow_value}}}\n"
    )
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/name", value="new")],
    )

    assert document.read_text("config.yaml") == yaml_text.replace("name: old", "name: new")


@pytest.mark.parametrize(
    ("key", "nested"),
    [
        ("[a, # KEEP\n  b]", False),
        ("[a, # KEEP\n    b]", True),
        ("{a: x, # KEEP\n  b: y}", False),
        ("{a: x, # KEEP\n    b: y}", True),
    ],
    ids=["sequence-key", "nested-sequence-key", "mapping-key", "nested-mapping-key"],
)
def test_replace_preserves_comment_inside_flow_collection_mapping_key(
    key: str,
    nested: bool,
) -> None:
    yaml_text = (
        f"name: old\nouter: {{m: {{? {key}: v}}}}\n"
        if nested
        else f"name: old\nm: {{? {key}: v}}\n"
    )
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/name", value="new")],
    )

    assert document.read_text("config.yaml") == yaml_text.replace("name: old", "name: new")


def test_replace_file_preserves_invalid_yaml_verbatim() -> None:
    document = BundleDocument({"config.yaml": b"name: valid\n"})
    invalid_yaml = "name: [not closed\n  exact spacing"

    apply_patches(
        document,
        [
            BundlePatch(
                file="config.yaml",
                op="replace_file",
                value=invalid_yaml,
            )
        ],
    )

    assert document.read_text("config.yaml") == invalid_yaml


def test_add_accepts_a_missing_mapping_key() -> None:
    document = BundleDocument({"config.yaml": b"name: agent\n"})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="add", path="/enabled", value=False)],
    )

    assert document.yaml_value("config.yaml", ("enabled",)) is False


@pytest.mark.parametrize(
    ("yaml_text", "path", "expected"),
    [
        (
            (
                "items:\n"
                "  - first # first inline\n"
                "  # keep second docs\n"
                "  - second # second inline\n"
            ),
            "/items/1",
            (
                "items:\n"
                "  - first # first inline\n"
                "  - inserted\n"
                "  # keep second docs\n"
                "  - second # second inline\n"
            ),
        ),
        (
            "items:\n  # keep first docs\n  - first\n  - second\n",
            "/items/0",
            "items:\n  - inserted\n  # keep first docs\n  - first\n  - second\n",
        ),
        (
            "items:\n  - first\n  # sequence footer\nafter: keep\n",
            "/items/-",
            "items:\n  - first\n  - inserted\n  # sequence footer\nafter: keep\n",
        ),
    ],
    ids=["insert-before-commented-successor", "insert-at-zero", "append-before-footer"],
)
def test_sequence_add_preserves_successor_and_footer_comment_owners(
    yaml_text: str,
    path: str,
    expected: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="add", path=path, value="inserted")],
    )

    assert document.read_text("config.yaml") == expected
    assert document.yaml_value("config.yaml", ("items",)) == (
        ["inserted", "first", "second"]
        if path == "/items/0"
        else ["first", "inserted", "second"]
        if path == "/items/1"
        else ["first", "inserted"]
    )


@pytest.mark.parametrize(
    ("value", "rendered_item"),
    [
        ({"key": "value"}, "  - key: value\n"),
        (["x", "y"], "  - - x\n    - y\n"),
        (None, "  - null\n"),
    ],
    ids=["mapping", "sequence", "null"],
)
@pytest.mark.parametrize(
    ("path", "before", "after"),
    [
        (
            "/items/0",
            "items:\n  # FIRST\n  - first # INLINE\nother: old\n",
            "items:\n{item}  # FIRST\n  - first # INLINE\nother: old\n",
        ),
        (
            "/items/1",
            "items:\n  - first # INLINE\n  # SECOND\n  - second\nother: old\n",
            "items:\n  - first # INLINE\n{item}  # SECOND\n  - second\nother: old\n",
        ),
        (
            "/items/-",
            "items:\n  - first # INLINE\n  # FOOTER\nother: old\n",
            "items:\n  - first # INLINE\n{item}  # FOOTER\nother: old\n",
        ),
    ],
    ids=["insert-zero", "insert-middle", "append"],
)
def test_sequence_add_composite_value_keeps_comment_owner_across_next_patch(
    value: object,
    rendered_item: str,
    path: str,
    before: str,
    after: str,
) -> None:
    document = BundleDocument({"config.yaml": before.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="add", path=path, value=value)],
    )
    expected = after.format(item=rendered_item)
    assert document.read_text("config.yaml") == expected

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/other", value="new")],
    )

    assert document.read_text("config.yaml") == expected.replace("other: old", "other: new")


@pytest.mark.parametrize("op", ["replace", "remove"])
def test_replace_and_remove_reject_a_missing_mapping_key(op: str) -> None:
    document = BundleDocument({"config.yaml": b"name: agent\n"})
    before = document.to_bytes()

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [BundlePatch(file="config.yaml", op=op, path="/missing", value="new")],  # type: ignore[arg-type]
        )

    _assert_sanitized(caught.value)
    assert document.to_bytes() == before


def test_array_add_replace_remove_and_append_follow_json_patch_rules() -> None:
    document = BundleDocument({"config.yaml": b"items: [first, second]\n"})

    apply_patches(
        document,
        [
            BundlePatch(file="config.yaml", op="add", path="/items/0", value="inserted"),
            BundlePatch(file="config.yaml", op="replace", path="/items/1", value="changed"),
            BundlePatch(file="config.yaml", op="remove", path="/items/2"),
            BundlePatch(file="config.yaml", op="add", path="/items/-", value="appended"),
        ],
    )

    assert document.yaml_value("config.yaml", ("items",)) == [
        "inserted",
        "changed",
        "appended",
    ]


@pytest.mark.parametrize(
    ("op", "path"),
    [
        ("add", "/items/3"),
        ("add", "/items/01"),
        ("add", "/items/-1"),
        ("add", "/items/+1"),
        ("add", "/items/١"),
        pytest.param("add", "/items/" + "9" * 5000, id="add-huge-index"),
        ("replace", "/items/-"),
        ("replace", "/items/2"),
        ("remove", "/items/-"),
        ("remove", "/items/2"),
    ],
)
def test_array_operations_reject_invalid_indices(op: str, path: str) -> None:
    document = BundleDocument({"config.yaml": b"items: [first, second]\n"})

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [BundlePatch(file="config.yaml", op=op, path=path, value="new")],  # type: ignore[arg-type]
        )

    _assert_sanitized(caught.value)


def test_json_pointer_decodes_slash_and_tilde_escapes() -> None:
    document = BundleDocument({"config.yaml": b"'a/b': old\n'm~n': old\n'~1': old\n"})

    apply_patches(
        document,
        [
            BundlePatch(file="config.yaml", op="replace", path="/a~1b", value="slash"),
            BundlePatch(file="config.yaml", op="replace", path="/m~0n", value="tilde"),
            BundlePatch(file="config.yaml", op="replace", path="/~01", value="escaped"),
        ],
    )

    assert document.yaml_value("config.yaml", ("a/b",)) == "slash"
    assert document.yaml_value("config.yaml", ("m~n",)) == "tilde"
    assert document.yaml_value("config.yaml", ("~1",)) == "escaped"


@pytest.mark.parametrize("path", ["missing-leading-slash", "/bad~2escape", "/bad~"])
def test_json_pointer_rejects_invalid_syntax_and_escapes(path: str) -> None:
    document = BundleDocument({"config.yaml": b"name: agent\n"})

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [BundlePatch(file="config.yaml", op="add", path=path, value="new")],
        )

    _assert_sanitized(caught.value)


def test_later_patch_failure_leaves_all_original_bytes_unchanged() -> None:
    document = BundleDocument(
        {"config.yaml": b"name: original\n", "notes.txt": b"original bytes\n"}
    )
    before = document.to_bytes()

    with pytest.raises(BundlePatchError):
        apply_patches(
            document,
            [
                BundlePatch(file="config.yaml", op="replace", path="/name", value="edited"),
                BundlePatch(file="notes.txt", op="replace_file", value="edited bytes\n"),
                BundlePatch(file="config.yaml", op="remove", path="/missing"),
            ],
        )

    assert document.to_bytes() == before
    assert document.read_text("config.yaml") == "name: original\n"
    assert document.read_text("notes.txt") == "original bytes\n"


def test_replace_and_delete_file() -> None:
    document = BundleDocument({"notes.txt": b"old\n", "delete.txt": b"remove me\n"})

    apply_patches(
        document,
        [
            BundlePatch(file="notes.txt", op="replace_file", value="new\n"),
            BundlePatch(file="delete.txt", op="delete_file"),
        ],
    )

    assert document.read_text("notes.txt") == "new\n"
    assert not document.exists("delete.txt")


@pytest.mark.parametrize("op", ["replace_file", "delete_file"])
def test_file_operations_reject_a_missing_file(op: str) -> None:
    document = BundleDocument({"keep.txt": b"keep\n"})

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [BundlePatch(file="missing.txt", op=op, value="new\n")],  # type: ignore[arg-type]
        )

    _assert_sanitized(caught.value)


@pytest.mark.parametrize(
    "file",
    [
        "/absolute.yaml",
        "../escape.yaml",
        "nested/../../escape.yaml",
        "bad\udcff.yaml",
        "C:/drive.yaml",
        "C:\\drive.yaml",
        "nested\\config.yaml",
        "nul\x00suffix.yaml",
        "\\\\server\\share\\config.yaml",
    ],
)
def test_patch_rejects_unsafe_file_paths(file: str) -> None:
    document = BundleDocument({"config.yaml": b"name: agent\n"})

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [BundlePatch(file=file, op="replace_file", value="secret contents")],
        )

    _assert_sanitized(caught.value)


def test_explicit_null_is_applied_but_an_omitted_required_value_is_rejected() -> None:
    document = BundleDocument({"config.yaml": b"setting: present\n"})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/setting", value=None)],
    )
    assert document.yaml_value("config.yaml", ("setting",)) is None

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [BundlePatch(file="config.yaml", op="add", path="/missing")],
        )

    _assert_sanitized(caught.value)


def test_replace_file_requires_a_utf8_string() -> None:
    document = BundleDocument({"notes.txt": b"old\n"})

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [BundlePatch(file="notes.txt", op="replace_file", value=b"new\n")],
        )

    _assert_sanitized(caught.value)


def test_patch_error_reports_location_without_leaking_values_or_file_contents() -> None:
    document = BundleDocument({"config.yaml": b"stored-super-secret\n"})
    secret_value = "requested-super-secret"

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [
                BundlePatch(
                    file="config.yaml",
                    op="replace",
                    path="/missing",
                    value=secret_value,
                )
            ],
        )

    error = caught.value
    assert error.file == "config.yaml"
    assert error.path == "/missing"
    _assert_sanitized(error)
    assert secret_value not in str(error)
    assert "stored-super-secret" not in str(error)


def test_runtime_error_from_value_deepcopy_is_sanitized() -> None:
    document = BundleDocument({"config.yaml": b"name: original\n"})

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [
                BundlePatch(
                    file="config.yaml",
                    op="replace",
                    path="/name",
                    value=_ExplodingDeepcopy(),
                )
            ],
        )

    _assert_sanitized(caught.value)
    assert "sensitive-deepcopy-detail" not in str(caught.value)


def test_recursion_error_from_deep_value_is_sanitized() -> None:
    document = BundleDocument({"config.yaml": b"name: original\n"})
    deeply_nested: object = "leaf"
    for _ in range(2000):
        deeply_nested = [deeply_nested]

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [
                BundlePatch(
                    file="config.yaml",
                    op="replace",
                    path="/name",
                    value=deeply_nested,
                )
            ],
        )

    _assert_sanitized(caught.value)


def test_base_exception_from_value_deepcopy_is_not_caught() -> None:
    document = BundleDocument({"config.yaml": b"name: original\n"})

    with pytest.raises(KeyboardInterrupt):
        apply_patches(
            document,
            [
                BundlePatch(
                    file="config.yaml",
                    op="replace",
                    path="/name",
                    value=_InterruptingDeepcopy(),
                )
            ],
        )


@pytest.mark.parametrize("op", ["add", "replace"])
def test_add_and_replace_support_the_yaml_document_root(op: str) -> None:
    document = BundleDocument({"config.yaml": b"name: original\nkeep: old\n"})

    apply_patches(
        document,
        [
            BundlePatch(
                file="config.yaml",
                op=op,
                value={"root": "replacement"},
            )  # type: ignore[arg-type]
        ],
    )

    assert document.yaml_value("config.yaml", ()) == {"root": "replacement"}


def test_remove_rejects_the_yaml_document_root_atomically() -> None:
    document = BundleDocument({"config.yaml": b"name: original\n"})
    before = document.to_bytes()

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(document, [BundlePatch(file="config.yaml", op="remove")])

    _assert_sanitized(caught.value)
    assert document.to_bytes() == before


def test_yaml_commit_invalidates_the_edited_file_cache() -> None:
    document = BundleDocument({"config.yaml": b"name: original\n"})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/name", value="edited")],
    )

    assert "config.yaml" not in document._yaml_documents


def test_yaml_candidate_validation_failure_does_not_write_file_or_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = BundleDocument(
        {"config.yaml": b"# header\nname: original # comment\nkeep: value\n"}
    )
    assert document.yaml_value("config.yaml", ("name",)) == "original"
    before_file = document.read_text("config.yaml")
    cached = document._yaml_documents["config.yaml"]

    def reject_candidate(rendered: bytes) -> None:
        del rendered
        raise ValueError("sensitive candidate validation detail")

    monkeypatch.setattr(
        BundleDocument,
        "_validate_yaml_candidate",
        staticmethod(reject_candidate),
        raising=False,
    )

    with pytest.raises(ValueError, match="sensitive candidate validation detail"):
        document.replace_yaml_value("config.yaml", ("name",), "edited")

    assert document.read_text("config.yaml") == before_file
    assert document._yaml_documents["config.yaml"] is cached
    assert document.yaml_value("config.yaml", ("name",)) == "original"


def test_yaml_candidate_validation_failure_is_sanitized_and_batch_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = BundleDocument(
        {"config.yaml": b"# header\nname: original # comment\nkeep: value\n"}
    )
    assert document.yaml_value("config.yaml", ("name",)) == "original"
    before = document.to_bytes()
    cached = document._yaml_documents["config.yaml"]

    def reject_candidate(rendered: bytes) -> None:
        del rendered
        raise ValueError("sensitive candidate validation detail")

    monkeypatch.setattr(
        BundleDocument,
        "_validate_yaml_candidate",
        staticmethod(reject_candidate),
        raising=False,
    )

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [BundlePatch(file="config.yaml", op="replace", path="/name", value="edited")],
        )

    _assert_sanitized(caught.value)
    assert "sensitive candidate validation detail" not in str(caught.value)
    assert document.to_bytes() == before
    assert document._yaml_documents["config.yaml"] is cached


def test_two_patches_in_one_batch_preserve_untouched_comments() -> None:
    document = BundleDocument(
        {
            "config.yaml": (
                b"# document header\n"
                b"first: original # first comment\n"
                b"second: original # second comment\n"
                b"untouched: keep # untouched comment\n"
            )
        }
    )

    apply_patches(
        document,
        [
            BundlePatch(file="config.yaml", op="replace", path="/first", value="one"),
            BundlePatch(file="config.yaml", op="replace", path="/second", value="two"),
        ],
    )

    rendered = document.read_text("config.yaml")
    assert "# document header" in rendered
    assert "untouched: keep # untouched comment" in rendered


def test_two_independent_apply_calls_preserve_untouched_comments() -> None:
    document = BundleDocument(
        {
            "config.yaml": (
                b"first: original # first comment\n"
                b"second: original # second comment\n"
                b"untouched: keep # untouched comment\n"
            )
        }
    )

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/first", value="one")],
    )
    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/second", value="two")],
    )

    assert "untouched: keep # untouched comment" in document.read_text("config.yaml")


def test_prewarmed_cache_remains_unchanged_after_later_patch_failure() -> None:
    document = BundleDocument(
        {"config.yaml": b"# header\nname: original # comment\nkeep: value\n"}
    )
    assert document.yaml_value("config.yaml", ("name",)) == "original"
    before_bytes = document.to_bytes()
    before_text = document.read_text("config.yaml")

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [
                BundlePatch(file="config.yaml", op="replace", path="/name", value="edited"),
                BundlePatch(
                    file="config.yaml",
                    op="replace",
                    path="/keep",
                    value=_ExplodingDeepcopy(),
                ),
            ],
        )

    _assert_sanitized(caught.value)
    assert document.to_bytes() == before_bytes
    assert document.read_text("config.yaml") == before_text
    assert document.yaml_value("config.yaml", ("name",)) == "original"


def test_merge_mapping_locator_replaces_the_explicit_key_not_the_merge_entry() -> None:
    yaml_text = "base: &base\n  a: 1\n  b: 2\nmerged:\n  <<: *base\n  c: old\n"
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/merged/c", value="new")],
    )

    assert document.read_text("config.yaml") == yaml_text.replace("c: old", "c: new")
    assert document.yaml_value("config.yaml", ("merged",)) == {"a": 1, "b": 2, "c": "new"}


@pytest.mark.parametrize("op", ["add", "replace"])
def test_merge_mapping_write_to_inherited_key_creates_an_explicit_override(op: str) -> None:
    yaml_text = "base: &base\n  a: old\nmerged:\n  <<: *base\n  c: keep\n"
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op=op, path="/merged/a", value="new")],  # type: ignore[arg-type]
    )

    assert document.read_text("config.yaml") == (
        "base: &base\n  a: old\nmerged:\n  <<: *base\n  c: keep\n  a: new\n"
    )
    assert document.yaml_value("config.yaml", ("base", "a")) == "old"
    assert document.yaml_value("config.yaml", ("merged", "a")) == "new"


def test_merge_mapping_remove_of_inherited_key_is_rejected_atomically() -> None:
    yaml_text = "base: &base\n  a: old\nmerged:\n  <<: *base\n  c: keep\n"
    document = BundleDocument({"config.yaml": yaml_text.encode()})
    before = document.to_bytes()

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [BundlePatch(file="config.yaml", op="remove", path="/merged/a")],
        )

    _assert_sanitized(caught.value)
    assert document.to_bytes() == before
    assert document.read_text("config.yaml") == yaml_text


def test_flow_merge_mapping_remove_uses_the_explicit_pair_count() -> None:
    yaml_text = "base: &base {a: 1, b: 2}\nmerged: {<<: *base, c: 3}\n"
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path="/merged/c")],
    )

    assert document.read_text("config.yaml") == ("base: &base {a: 1, b: 2}\nmerged: {<<: *base}\n")


@pytest.mark.parametrize(
    ("yaml_text", "value", "expected"),
    [
        (
            "value: &v old\nuse: *v\n",
            "new",
            "value: &v old\nuse: new\n",
        ),
        (
            "value: &v {a: 1}\nuse: *v\n",
            {"b": 2},
            "value: &v {a: 1}\nuse: {b: 2}\n",
        ),
    ],
    ids=["scalar-alias", "mapping-alias"],
)
def test_replace_alias_edits_the_alias_occurrence_not_the_anchor(
    yaml_text: str,
    value: object,
    expected: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="replace", path="/use", value=value)],
    )

    assert document.read_text("config.yaml") == expected


@pytest.mark.parametrize(
    "yaml_text",
    [
        "value: &v old\nuse: *v\n",
        "value: &v {a: 1}\nuse: *v\n",
    ],
    ids=["scalar-anchor", "mapping-anchor"],
)
def test_remove_anchor_with_live_alias_is_rejected_atomically(yaml_text: str) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})
    before = document.to_bytes()

    with pytest.raises(BundlePatchError) as caught:
        apply_patches(
            document,
            [BundlePatch(file="config.yaml", op="remove", path="/value")],
        )

    _assert_sanitized(caught.value)
    assert document.to_bytes() == before
    assert document.read_text("config.yaml") == yaml_text


def test_root_sequence_insert_zero_keeps_header_before_new_item_and_first_docs() -> None:
    yaml_text = "# DOCUMENT HEADER\n\n# FIRST DOCS\n- first\n"
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="add", path="/0", value="inserted")],
    )

    assert document.read_text("config.yaml") == (
        "# DOCUMENT HEADER\n\n- inserted\n# FIRST DOCS\n- first\n"
    )


@pytest.mark.parametrize(
    ("yaml_text", "path", "expected"),
    [
        (
            "items: [ # FIRST\n  first, second]\n",
            "/items/0",
            "items: [ inserted, # FIRST\n  first, second]\n",
        ),
        (
            "items: [first, # SECOND\n  second]\n",
            "/items/1",
            "items: [first, inserted, # SECOND\n  second]\n",
        ),
        (
            "items: [first, second, # FOOTER\n]\n",
            "/items/-",
            "items: [first, second, inserted, # FOOTER\n]\n",
        ),
    ],
    ids=["first", "middle", "append-before-footer"],
)
def test_flow_sequence_add_preserves_successor_and_footer_comment_owner(
    yaml_text: str,
    path: str,
    expected: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="add", path=path, value="inserted")],
    )

    assert document.read_text("config.yaml") == expected


@pytest.mark.parametrize(
    ("yaml_text", "expected"),
    [
        (
            "items: { # FOOTER\n}\n",
            "items: { added: value, # FOOTER\n}\n",
        ),
        (
            "items: {a: 1, # FOOTER\n}\n",
            "items: {a: 1, added: value, # FOOTER\n}\n",
        ),
    ],
    ids=["empty", "append"],
)
def test_flow_mapping_add_inserts_before_pre_close_footer(
    yaml_text: str,
    expected: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="add", path="/items/added", value="value")],
    )

    assert document.read_text("config.yaml") == expected


@pytest.mark.parametrize(
    ("yaml_text", "path", "expected"),
    [
        ("first: one", "/second", "first: one\nsecond: two\n"),
        ("outer:\n  first: one", "/outer/second", "outer:\n  first: one\n  second: two\n"),
        ("- one", "/-", "- one\n- two\n"),
        ("outer:\n  - one", "/outer/-", "outer:\n  - one\n  - two\n"),
    ],
    ids=["root-mapping", "nested-mapping", "root-sequence", "nested-sequence"],
)
def test_block_add_does_not_join_fragment_to_source_without_final_newline(
    yaml_text: str,
    path: str,
    expected: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="add", path=path, value="two")],
    )

    assert document.read_text("config.yaml") == expected


@pytest.mark.parametrize(
    ("yaml_text", "path", "expected"),
    [
        ("first: one\r\n", "/second", "first: one\r\nsecond: two\r\n"),
        (
            "outer:\r\n  first: one\r\n",
            "/outer/second",
            "outer:\r\n  first: one\r\n  second: two\r\n",
        ),
        ("- one\r\n", "/-", "- one\r\n- two\r\n"),
        (
            "outer:\r\n  - one\r\n",
            "/outer/-",
            "outer:\r\n  - one\r\n  - two\r\n",
        ),
    ],
    ids=["root-mapping", "nested-mapping", "root-sequence", "nested-sequence"],
)
def test_block_add_uses_the_collection_crlf_newline_style(
    yaml_text: str,
    path: str,
    expected: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="add", path=path, value="two")],
    )

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    assert "\n" not in rendered.replace("\r\n", "")


@pytest.mark.parametrize(
    ("yaml_text", "op", "value", "expected"),
    [
        (
            'anchor: &v "KEEP"\nitems:\n  - *v\n  - tail\n',
            "replace",
            "changed",
            'anchor: &v "KEEP"\nitems:\n  - changed\n  - tail\n',
        ),
        (
            'anchor: &v "KEEP"\nitems: [*v, tail]\n',
            "replace",
            "changed",
            'anchor: &v "KEEP"\nitems: [changed, tail]\n',
        ),
        (
            'anchor: &v "KEEP"\nitems:\n  - *v\n  - tail\n',
            "remove",
            None,
            'anchor: &v "KEEP"\nitems:\n  - tail\n',
        ),
        (
            'anchor: &v "KEEP"\nitems: [*v, tail]\n',
            "remove",
            None,
            'anchor: &v "KEEP"\nitems: [tail]\n',
        ),
        (
            'anchor: &v "KEEP"\nitems:\n  - *v\n  - tail\n',
            "add",
            "inserted",
            'anchor: &v "KEEP"\nitems:\n  - inserted\n  - *v\n  - tail\n',
        ),
        (
            'anchor: &v "KEEP"\nitems: [*v, tail]\n',
            "add",
            "inserted",
            'anchor: &v "KEEP"\nitems: [inserted, *v, tail]\n',
        ),
    ],
    ids=[
        "block-replace",
        "flow-replace",
        "block-remove",
        "flow-remove",
        "block-add-before",
        "flow-add-before",
    ],
)
def test_sequence_alias_operations_splice_the_alias_occurrence(
    yaml_text: str,
    op: str,
    value: object,
    expected: str,
) -> None:
    anchor_definition = 'anchor: &v "KEEP"\n'
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op=op, path="/items/0", value=value)],  # type: ignore[arg-type]
    )

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    assert rendered[: len(anchor_definition)] == anchor_definition


@pytest.mark.parametrize(
    ("yaml_text", "expected"),
    [
        (
            "# HEADER\n---\n# FIRST\n- first\n",
            "# HEADER\n---\n- inserted\n# FIRST\n- first\n",
        ),
        (
            "# FIRST\n- first\n",
            "- inserted\n# FIRST\n- first\n",
        ),
        (
            "# HEADER A\n# HEADER B\n\n# FIRST A\n# FIRST B\n- first\n",
            "# HEADER A\n# HEADER B\n\n- inserted\n# FIRST A\n# FIRST B\n- first\n",
        ),
    ],
    ids=["explicit-document", "single-first-comment", "complete-first-comment-group"],
)
def test_root_sequence_insert_zero_preserves_the_complete_first_comment_group(
    yaml_text: str,
    expected: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="add", path="/0", value="inserted")],
    )

    assert document.read_text("config.yaml") == expected


@pytest.mark.parametrize(
    ("yaml_text", "anchor_definition", "expected"),
    [
        (
            'owner: &v "KEEP"\nitems: {alias: *v}\n',
            'owner: &v "KEEP"',
            'owner: &v "KEEP"\nitems: {}\n',
        ),
        (
            "owner: &v {nested: [one, two]}\nitems: {first: keep, alias: *v}\n",
            "owner: &v {nested: [one, two]}",
            "owner: &v {nested: [one, two]}\nitems: {first: keep}\n",
        ),
        (
            'items: {owner: &v "KEEP", between: [one, two], alias: *v}\n',
            'owner: &v "KEEP"',
            'items: {owner: &v "KEEP", between: [one, two]}\n',
        ),
    ],
    ids=["single-scalar-owner", "last-flow-owner", "same-mapping-with-commas"],
)
def test_flow_mapping_remove_splices_the_alias_occurrence(
    yaml_text: str,
    anchor_definition: str,
    expected: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path="/items/alias")],
    )

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    assert anchor_definition in rendered


@pytest.mark.parametrize(
    ("yaml_text", "anchor_definition", "expected"),
    [
        (
            'owner: &v "KEEP"\nnested:\n  alias: *v\nroot: stay\n',
            'owner: &v "KEEP"',
            'owner: &v "KEEP"\nnested:\n  alias: *v\n  added: one\n  second: two\nroot: stay\n',
        ),
        (
            "owner: &v {nested: [one, two]}\n"
            "nested:\n"
            "  first: keep\n"
            "  alias: *v\n"
            "# ROOT DOCS\n"
            "root: stay\n",
            "owner: &v {nested: [one, two]}",
            "owner: &v {nested: [one, two]}\n"
            "nested:\n"
            "  first: keep\n"
            "  alias: *v\n"
            "  added: one\n"
            "  second: two\n"
            "# ROOT DOCS\n"
            "root: stay\n",
        ),
        (
            "nested:\n  owner: &v [one, two]\n  first: keep\n  alias: *v\nroot: stay\n",
            "owner: &v [one, two]",
            "nested:\n"
            "  owner: &v [one, two]\n"
            "  first: keep\n"
            "  alias: *v\n"
            "  added: one\n"
            "  second: two\n"
            "root: stay\n",
        ),
    ],
    ids=["unique-scalar-owner", "last-mapping-owner-footer", "same-mapping-sequence-owner"],
)
def test_block_mapping_append_after_alias_uses_the_occurrence_end(
    yaml_text: str,
    anchor_definition: str,
    expected: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [
            BundlePatch(file="config.yaml", op="add", path="/nested/added", value="one"),
            BundlePatch(file="config.yaml", op="add", path="/nested/second", value="two"),
        ],
    )

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    assert anchor_definition in rendered


@pytest.mark.parametrize(
    ("yaml_text", "path", "second_path", "expected"),
    [
        (
            "items:\r\n  - old\r\n  - tail\r\n",
            "/items/0",
            "/items/0/third",
            "items:\r\n  - first: 1\r\n    second: 2\r\n    third: 3\r\n  - tail\r\n",
        ),
        (
            "item:\r\n  old\r\nsuccessor: keep\r\n",
            "/item",
            "/item/third",
            "item:\r\n  first: 1\r\n  second: 2\r\n  third: 3\r\nsuccessor: keep\r\n",
        ),
    ],
    ids=["block-sequence-composite", "block-mapping-multiline-value"],
)
def test_composite_replace_preserves_crlf_across_the_next_patch(
    yaml_text: str,
    path: str,
    second_path: str,
    expected: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [
            BundlePatch(
                file="config.yaml",
                op="replace",
                path=path,
                value={"first": 1, "second": 2},
            ),
            BundlePatch(file="config.yaml", op="add", path=second_path, value=3),
        ],
    )

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    assert "\n" not in rendered.replace("\r\n", "")


@pytest.mark.parametrize(
    ("yaml_text", "anchor_definition", "expected"),
    [
        (
            'owner: &v "KEEP"\nnoise: [one, two]\nitems: {alias: *v, target: remove}\n',
            'owner: &v "KEEP"',
            'owner: &v "KEEP"\nnoise: [one, two]\nitems: {alias: *v}\n',
        ),
        (
            "owner: &v {one: 1, two: 2}\nitems: {alias: *v, target: remove}\n",
            "owner: &v {one: 1, two: 2}",
            "owner: &v {one: 1, two: 2}\nitems: {alias: *v}\n",
        ),
        (
            "owner: &v [one, two]\nitems: {alias: *v, target: remove}\n",
            "owner: &v [one, two]",
            "owner: &v [one, two]\nitems: {alias: *v}\n",
        ),
        (
            'items: {owner: &v "KEEP", noise: [one, two], alias: *v, target: remove}\n',
            'owner: &v "KEEP"',
            'items: {owner: &v "KEEP", noise: [one, two], alias: *v}\n',
        ),
        (
            "items: {owner: &v {one: 1, two: 2}, alias: *v, target: remove}\n",
            "owner: &v {one: 1, two: 2}",
            "items: {owner: &v {one: 1, two: 2}, alias: *v}\n",
        ),
        (
            "items: {owner: &v [one, two], alias: *v, target: remove}\n",
            "owner: &v [one, two]",
            "items: {owner: &v [one, two], alias: *v}\n",
        ),
    ],
    ids=[
        "external-scalar-owner",
        "external-mapping-owner",
        "external-sequence-owner",
        "inner-scalar-owner",
        "inner-mapping-owner",
        "inner-sequence-owner",
    ],
)
def test_flow_mapping_remove_last_after_alias_uses_the_entry_separator(
    yaml_text: str,
    anchor_definition: str,
    expected: str,
) -> None:
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path="/items/target")],
    )

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    assert anchor_definition in rendered


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_flow_mapping_remove_nonfinal_uses_the_same_depth_separator(
    newline: str,
) -> None:
    yaml_text = newline.join(
        [
            "owner: &v {stable: [one, two]}",
            "items: {alias: *v, target: [remove, {nested: value}] # fake, comma",
            ", successor: {kept: [one, two]}}",
            "",
        ]
    )
    expected = newline.join(
        [
            "owner: &v {stable: [one, two]}",
            "items: {alias: *v, successor: {kept: [one, two]}}",
            "",
        ]
    )
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path="/items/target")],
    )

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    assert document.yaml_value("config.yaml", ["items"]) == {
        "alias": {"stable": ["one", "two"]},
        "successor": {"kept": ["one", "two"]},
    }
    assert "# fake, comma" not in rendered
    if newline == "\r\n":
        assert "\n" not in rendered.replace("\r\n", "")


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_flow_mapping_remove_final_with_trailing_separator_drops_its_comment(
    newline: str,
) -> None:
    yaml_text = newline.join(
        [
            'owner: &v "KEEP"',
            "items: {alias: *v, target: [remove, {nested: value}] # target inline",
            ",}",
            "",
        ]
    )
    expected = newline.join(
        [
            'owner: &v "KEEP"',
            "items: {alias: *v}",
            "",
        ]
    )
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path="/items/target")],
    )

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    items = document.yaml_value("config.yaml", ["items"])
    assert items == {"alias": "KEEP"}
    assert items.ca.items.get("alias") is None
    assert "# target inline" not in rendered
    if newline == "\r\n":
        assert "\n" not in rendered.replace("\r\n", "")


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("collection_kind", ["mapping", "sequence"])
def test_remove_only_flow_item_with_trailing_separator_drops_its_comment(
    newline: str,
    collection_kind: str,
) -> None:
    if collection_kind == "mapping":
        lines = [
            "items: {target: [remove, {nested: value}] # target inline",
            ",}",
            "root: stay",
            "",
        ]
        expected_lines = ["items: {}", "root: stay", ""]
        path = "/items/target"
        expected_value: object = {}
    else:
        lines = [
            "owner: &v {nested: [remove, value]}",
            "items: [*v # target inline",
            ",]",
            "root: stay",
            "",
        ]
        expected_lines = [
            "owner: &v {nested: [remove, value]}",
            "items: []",
            "root: stay",
            "",
        ]
        path = "/items/0"
        expected_value = []
    yaml_text = newline.join(lines)
    expected = newline.join(expected_lines)
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path=path)],
    )

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    assert document.yaml_value("config.yaml", ["items"]) == expected_value
    assert "# target inline" not in rendered
    if newline == "\r\n":
        assert "\n" not in rendered.replace("\r\n", "")


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("collection_kind", ["mapping", "sequence"])
def test_remove_only_flow_item_without_trailing_separator_drops_its_comment(
    newline: str,
    collection_kind: str,
) -> None:
    if collection_kind == "mapping":
        lines = [
            "items: {target: {nested: [remove, value]} # TARGET INLINE",
            "} # CLOSING FOOTER",
            "root: stay",
            "",
        ]
        expected_lines = ["items: {} # CLOSING FOOTER", "root: stay", ""]
        path = "/items/target"
        expected_value: object = {"items": {}, "root": "stay"}
    else:
        lines = [
            "owner: &v {nested: [remove, value]}",
            "items: [*v # TARGET INLINE",
            "] # CLOSING FOOTER",
            "root: stay",
            "",
        ]
        expected_lines = [
            "owner: &v {nested: [remove, value]}",
            "items: [] # CLOSING FOOTER",
            "root: stay",
            "",
        ]
        path = "/items/0"
        expected_value = {
            "owner": {"nested": ["remove", "value"]},
            "items": [],
            "root": "stay",
        }
    yaml_text = newline.join(lines)
    expected = newline.join(expected_lines)
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path=path)],
    )

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    root = document.yaml_value("config.yaml", ())
    assert root == expected_value
    assert root.ca.items["items"][2].value.strip() == "# CLOSING FOOTER"
    assert "# TARGET INLINE" not in rendered
    if newline == "\r\n":
        assert "\n" not in rendered.replace("\r\n", "")


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("collection_kind", ["mapping", "sequence"])
def test_remove_final_flow_alias_without_trailing_separator_drops_its_comment(
    newline: str,
    collection_kind: str,
) -> None:
    if collection_kind == "mapping":
        lines = [
            'owner: &v "REMOVE"',
            "items: {keep: {nested: [one, two]}, target: *v # target inline",
            "}",
            "root: stay",
            "",
        ]
        intermediate_lines = [
            'owner: &v "REMOVE"',
            "items: {keep: {nested: [one, two]}}",
            "root: stay",
            "",
        ]
        final_lines = [
            'owner: &v "REMOVE"',
            "items: {keep: {nested: [one, two]}, added: after}",
            "root: stay",
            "",
        ]
        remove_path = "/items/target"
        add_path = "/items/added"
        expected_intermediate: object = {"keep": {"nested": ["one", "two"]}}
        expected_final: object = {
            "keep": {"nested": ["one", "two"]},
            "added": "after",
        }
    else:
        lines = [
            'owner: &v "REMOVE"',
            "items: [{nested: [one, two]}, *v # target inline",
            "]",
            "root: stay",
            "",
        ]
        intermediate_lines = [
            'owner: &v "REMOVE"',
            "items: [{nested: [one, two]}]",
            "root: stay",
            "",
        ]
        final_lines = [
            'owner: &v "REMOVE"',
            "items: [{nested: [one, two]}, after]",
            "root: stay",
            "",
        ]
        remove_path = "/items/1"
        add_path = "/items/-"
        expected_intermediate = [{"nested": ["one", "two"]}]
        expected_final = [{"nested": ["one", "two"]}, "after"]
    yaml_text = newline.join(lines)
    intermediate = newline.join(intermediate_lines)
    expected = newline.join(final_lines)
    document = BundleDocument({"config.yaml": yaml_text.encode()})

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="remove", path=remove_path)],
    )

    rendered = document.read_text("config.yaml")
    assert rendered == intermediate
    items = document.yaml_value("config.yaml", ["items"])
    assert items == expected_intermediate
    predecessor = "keep" if collection_kind == "mapping" else 0
    assert items.ca.items.get(predecessor) is None
    assert "# target inline" not in rendered

    apply_patches(
        document,
        [BundlePatch(file="config.yaml", op="add", path=add_path, value="after")],
    )

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    items = document.yaml_value("config.yaml", ["items"])
    assert items == expected_final
    assert items.ca.items.get(predecessor) is None
    added = "added" if collection_kind == "mapping" else 1
    assert items.ca.items.get(added) is None
    if newline == "\r\n":
        assert "\n" not in rendered.replace("\r\n", "")


@pytest.mark.parametrize(
    ("parent_kind", "collection_kind", "op"),
    [
        ("mapping", "mapping", "add"),
        ("mapping", "mapping", "remove"),
        ("mapping", "sequence", "add"),
        ("mapping", "sequence", "remove"),
        ("sequence", "mapping", "add"),
        ("sequence", "mapping", "remove"),
        ("sequence", "sequence", "add"),
        ("sequence", "sequence", "remove"),
    ],
)
def test_block_collection_edits_include_the_multiline_flow_closing_delimiter(
    parent_kind: str,
    collection_kind: str,
    op: str,
) -> None:
    if collection_kind == "mapping":
        collection = "{\n    one: 1,\n    two: 2,\n  } # CHILD FOOTER"
        collection_value: object = {"one": 1, "two": 2}
    else:
        collection = "[\n    one,\n    two,\n  ] # CHILD FOOTER"
        collection_value = ["one", "two"]

    if parent_kind == "mapping":
        yaml_text = (
            f"items:\n  keep: before\n  target: {collection}\n# PARENT FOOTER\nroot: stay\n"
        )
        if op == "add":
            path = "/items/added"
            expected = yaml_text.replace(
                "# PARENT FOOTER",
                "  added: value\n# PARENT FOOTER",
            )
            expected_value = {
                "keep": "before",
                "target": collection_value,
                "added": "value",
            }
        else:
            path = "/items/target"
            expected = "items:\n  keep: before\n# PARENT FOOTER\nroot: stay\n"
            expected_value = {"keep": "before"}
    else:
        yaml_text = f"items:\n  - before\n  - {collection}\n# PARENT FOOTER\nroot: stay\n"
        if op == "add":
            path = "/items/-"
            expected = yaml_text.replace(
                "# PARENT FOOTER",
                "  - value\n# PARENT FOOTER",
            )
            expected_value = ["before", collection_value, "value"]
        else:
            path = "/items/1"
            expected = "items:\n  - before\n# PARENT FOOTER\nroot: stay\n"
            expected_value = ["before"]

    if parent_kind == "sequence":
        yaml_text = yaml_text.replace("\n", "\r\n")
        expected = expected.replace("\n", "\r\n")
    document = BundleDocument({"config.yaml": yaml_text.encode()})
    patch = (
        BundlePatch(file="config.yaml", op="add", path=path, value="value")
        if op == "add"
        else BundlePatch(file="config.yaml", op="remove", path=path)
    )

    apply_patches(document, [patch])

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    assert document.yaml_value("config.yaml", ["items"]) == expected_value
    if parent_kind == "sequence":
        assert "\n" not in rendered.replace("\r\n", "")


@pytest.mark.parametrize(
    ("parent_kind", "last_kind"),
    [
        ("mapping", "mapping"),
        ("mapping", "sequence"),
        ("mapping", "alias"),
        ("sequence", "mapping"),
        ("sequence", "sequence"),
        ("sequence", "alias"),
    ],
)
def test_block_append_keeps_deep_footer_with_the_last_child(
    parent_kind: str,
    last_kind: str,
) -> None:
    owner = 'owner: &v "KEEP"\n' if last_kind == "alias" else ""
    if parent_kind == "mapping":
        last = {
            "mapping": "  last:\n    child: value\n",
            "sequence": "  last:\n    - value\n",
            "alias": "  last: *v\n",
        }[last_kind]
        yaml_text = f"{owner}items:\n{last}    # CHILD FOOTER\n  # PARENT FOOTER\nroot: stay\n"
        expected = yaml_text.replace(
            "  # PARENT FOOTER",
            "  added: one\n  second: two\n  # PARENT FOOTER",
        )
        patches = [
            BundlePatch(file="config.yaml", op="add", path="/items/added", value="one"),
            BundlePatch(file="config.yaml", op="add", path="/items/second", value="two"),
        ]
    else:
        last = {
            "mapping": "  - child: value\n",
            "sequence": "  - - value\n",
            "alias": "  - *v\n",
        }[last_kind]
        yaml_text = f"{owner}items:\n{last}    # CHILD FOOTER\n  # PARENT FOOTER\nroot: stay\n"
        expected = yaml_text.replace(
            "  # PARENT FOOTER",
            "  - one\n  - two\n  # PARENT FOOTER",
        )
        patches = [
            BundlePatch(file="config.yaml", op="add", path="/items/-", value="one"),
            BundlePatch(file="config.yaml", op="add", path="/items/-", value="two"),
        ]

    document = BundleDocument({"config.yaml": yaml_text.encode()})
    apply_patches(document, patches)

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    if owner:
        assert rendered.startswith(owner)

    items = document.yaml_value("config.yaml", ["items"])
    if parent_kind == "mapping":
        parent_footer = items.ca.items["second"][2]
        if last_kind == "alias":
            child_footer = items.ca.items["added"][1][0]
        else:
            last_value = items["last"]
            child_footer = (
                last_value.ca.items["child"][2]
                if last_kind == "mapping"
                else last_value.ca.items[0][0]
            )
    else:
        parent_footer = items.ca.items[2][0]
        if last_kind == "alias":
            child_footer = items.ca.items[1][1][0]
        else:
            last_value = items[0]
            child_footer = (
                last_value.ca.items["child"][2]
                if last_kind == "mapping"
                else last_value.ca.items[0][0]
            )
    assert child_footer.value.strip() == "# CHILD FOOTER"
    assert parent_footer.value.strip() == "# PARENT FOOTER"


@pytest.mark.parametrize(
    ("parent_kind", "last_kind"),
    [
        ("mapping", "mapping"),
        ("mapping", "sequence"),
        ("mapping", "alias"),
        ("sequence", "mapping"),
        ("sequence", "sequence"),
        ("sequence", "alias"),
    ],
)
def test_block_append_keeps_blank_separated_deep_footers_with_the_last_child(
    parent_kind: str,
    last_kind: str,
) -> None:
    owner = 'owner: &v "KEEP"\n' if last_kind == "alias" else ""
    last_value: object = {
        "mapping": {"child": "value"},
        "sequence": ["value"],
        "alias": "KEEP",
    }[last_kind]
    if parent_kind == "mapping":
        last = {
            "mapping": "  last:\n    child: value\n",
            "sequence": "  last:\n    - value\n",
            "alias": "  last: *v\n",
        }[last_kind]
        yaml_text = (
            f"{owner}items:\n{last}"
            "\n    # CHILD FOOTER A\n\n\n      # CHILD FOOTER B\n"
            "  # PARENT FOOTER\nroot: stay\n"
        )
        expected = yaml_text.replace(
            "  # PARENT FOOTER",
            "  added: one\n  second: two\n  # PARENT FOOTER",
        )
        patches = [
            BundlePatch(file="config.yaml", op="add", path="/items/added", value="one"),
            BundlePatch(file="config.yaml", op="add", path="/items/second", value="two"),
        ]
        expected_value = {
            "last": last_value,
            "added": "one",
            "second": "two",
        }
    else:
        last = {
            "mapping": "  - child: value\n",
            "sequence": "  - - value\n",
            "alias": "  - *v\n",
        }[last_kind]
        yaml_text = (
            f"{owner}items:\n{last}"
            "\n    # CHILD FOOTER A\n\n\n      # CHILD FOOTER B\n"
            "  # PARENT FOOTER\nroot: stay\n"
        )
        expected = yaml_text.replace(
            "  # PARENT FOOTER",
            "  - one\n  - two\n  # PARENT FOOTER",
        )
        patches = [
            BundlePatch(file="config.yaml", op="add", path="/items/-", value="one"),
            BundlePatch(file="config.yaml", op="add", path="/items/-", value="two"),
        ]
        expected_value = [last_value, "one", "two"]
        yaml_text = yaml_text.replace("\n", "\r\n")
        expected = expected.replace("\n", "\r\n")

    document = BundleDocument({"config.yaml": yaml_text.encode()})
    apply_patches(document, patches)

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    assert document.yaml_value("config.yaml", ["items"]) == expected_value
    if parent_kind == "sequence":
        assert "\n" not in rendered.replace("\r\n", "")

    items = document.yaml_value("config.yaml", ["items"])
    if parent_kind == "mapping":
        parent_footer = items.ca.items["second"][2]
        if last_kind == "alias":
            child_footer = "".join(comment.value for comment in items.ca.items["added"][1])
        else:
            nested = items["last"]
            child_footer = (
                nested.ca.items["child"][2].value
                if last_kind == "mapping"
                else nested.ca.items[0][0].value
            )
    else:
        parent_footer = items.ca.items[2][0]
        if last_kind == "alias":
            child_footer = "".join(comment.value for comment in items.ca.items[1][1])
        else:
            nested = items[0]
            child_footer = (
                nested.ca.items["child"][2].value
                if last_kind == "mapping"
                else nested.ca.items[0][0].value
            )
    assert "# CHILD FOOTER A" in child_footer
    assert "# CHILD FOOTER B" in child_footer
    assert parent_footer.value.strip() == "# PARENT FOOTER"


@pytest.mark.parametrize("parent_kind", ["mapping", "sequence"])
def test_block_append_stops_before_blanks_leading_to_parent_footer(
    parent_kind: str,
) -> None:
    if parent_kind == "mapping":
        yaml_text = "items:\n  last:\n    child: value\n\n\n  # PARENT FOOTER\nroot: stay\n"
        expected = yaml_text.replace(
            "\n\n\n  # PARENT FOOTER",
            "\n  added: one\n\n\n  # PARENT FOOTER",
        )
        patch = BundlePatch(
            file="config.yaml",
            op="add",
            path="/items/added",
            value="one",
        )
    else:
        yaml_text = "items:\n  - child: value\n\n\n  # PARENT FOOTER\nroot: stay\n"
        expected = yaml_text.replace(
            "\n\n\n  # PARENT FOOTER",
            "\n  - one\n\n\n  # PARENT FOOTER",
        )
        patch = BundlePatch(file="config.yaml", op="add", path="/items/-", value="one")

    document = BundleDocument({"config.yaml": yaml_text.encode()})
    apply_patches(document, [patch])

    rendered = document.read_text("config.yaml")
    assert rendered == expected
    items = document.yaml_value("config.yaml", ["items"])
    parent_footer = (
        items.ca.items["added"][2] if parent_kind == "mapping" else items.ca.items[1][0]
    )
    assert parent_footer.value == "\n\n\n  # PARENT FOOTER\n"
