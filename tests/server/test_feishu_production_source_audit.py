"""RED source-audit contracts for the standalone Feishu cutover."""

from __future__ import annotations

from pathlib import Path

from omnigent.server.app import create_app

CORE_PRODUCTION_ROOTS = (
    Path("omnigent/server"),
    Path("omnigent/runs"),
    Path("omnigent/runner"),
)

FORBIDDEN_IMPORT_FRAGMENTS = (
    "omnigent.integrations.lark",
    "omnigent_feishu",
)

FORBIDDEN_APP_LIFECYCLE_FRAGMENTS = (
    "lark_adapter",
    "FeishuCredentialCipher",
    "FeishuPersonalAgentDeviceFlow",
    "create_feishu_router",
    "_save_feishu_installation",
)


def _production_sources() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for root in CORE_PRODUCTION_ROOTS
        for path in root.rglob("*.py")
    }


def test_core_production_import_graph_has_no_embedded_provider_packages() -> None:
    violations = {
        str(path): fragment
        for path, source in _production_sources().items()
        for fragment in FORBIDDEN_IMPORT_FRAGMENTS
        if fragment in source
    }

    assert violations == {}


def test_create_app_source_has_no_embedded_feishu_lifecycle() -> None:
    app_source = Path("omnigent/server/app.py").read_text(encoding="utf-8")
    violations = [
        fragment for fragment in FORBIDDEN_APP_LIFECYCLE_FRAGMENTS if fragment in app_source
    ]

    assert violations == []
    assert "lark_adapter" not in create_app.__annotations__


def test_core_proxy_module_is_provider_neutral_and_does_not_hold_run_service() -> None:
    proxy_path = Path("omnigent/server/routes/feishu_proxy.py")
    assert proxy_path.is_file(), "provider-neutral Core Feishu proxy module is missing"
    source = proxy_path.read_text(encoding="utf-8")

    assert "omnigent.integrations.lark" not in source
    assert "omnigent_feishu" not in source
    assert "RunService" not in source
    assert "SqlFeishu" not in source
