"""
Shared helpers for exposing an agent bundle's skills to a Claude harness.

Both the Claude Agent SDK executor (in-process, ``claude_sdk_executor``)
and the ``claude-native`` CLI launch path expose a bundle's
``skills/<name>/SKILL.md`` files to Claude Code. Native uses the plugin
convention when host skills are enabled. With ``skills: none`` it disables
all slash-command skills and exposes only the bundle's instruction files for
on-demand reads; this preserves Claude's user setting source because OAuth is
also gated by ``--setting-sources``.
"""

from __future__ import annotations

import json
from pathlib import Path


def ensure_bundle_plugin_manifest(
    bundle_dir: Path,
    agent_name: str | None,
) -> None:
    """
    Write a minimal ``<bundle>/.claude-plugin/plugin.json`` manifest
    when one isn't already present.

    Idempotent — if the file already exists (including with a
    user-supplied richer manifest), it's left untouched. The
    manifest gives the bundle a stable plugin name so Claude's
    skill listing labels bundled skills as
    ``<agent-name>:<skill-name>`` instead of falling back to the
    bundle's auto-generated tmp-dir basename
    (e.g. ``omnigent-ap-chat-x9p606iz/bundle:researcher``).

    :param bundle_dir: Materialized bundle root; the manifest is
        written at ``<bundle_dir>/.claude-plugin/plugin.json``.
    :param agent_name: Display name for the plugin. ``None`` falls
        back to the bundle directory's basename — still
        deterministic, just less readable.
    :returns: None.
    """
    manifest_dir = bundle_dir / ".claude-plugin"
    manifest_path = manifest_dir / "plugin.json"
    if manifest_path.exists():
        return
    manifest_dir.mkdir(parents=True, exist_ok=True)
    name = agent_name or bundle_dir.name
    manifest_path.write_text(
        json.dumps(
            {
                "name": name,
                "description": f"Bundled skills for omnigent agent {name!r}",
            },
            indent=2,
        )
        + "\n",
    )


def claude_native_skill_args(
    bundle_dir: Path | None,
    *,
    agent_name: str | None = None,
    skills_filter: str | list[str] = "all",
) -> list[str]:
    """
    Build the ``claude`` CLI args that expose bundle + host skills.

    This is the native-CLI mirror of the SDK's
    ``_resolve_skills_option`` + plugin wiring in
    ``claude_sdk_executor``. The real ``claude`` binary discovers a
    bundle's ``skills/<name>/SKILL.md`` files as plugin skills when the
    bundle is passed via ``--plugin-dir``, and gates host skills
    (``~/.claude/skills/``, project ``.claude/skills/``) via
    ``--setting-sources``. ``skills_filter`` maps the same way the SDK
    maps it onto ``setting_sources`` (matching the wrapped variants):

    - ``"all"`` → host skills included (the CLI's default setting
      sources), so no ``--setting-sources`` is emitted.
    - ``"none"`` → keep the ``user`` source for Claude OAuth, disable all
      slash-command skills, require the invocation MCP config, and expose the
      bundle as an explicit read root. :func:`claude_native_skill_prompt`
      supplies the corresponding on-demand Skill index.
    - ``list[str]`` → treated like ``"all"`` for host sources (the SDK
      uses ``setting_sources=None`` for the list case). The CLI has no
      per-name skill allowlist flag, so the named subset is not
      enforced on native — bundle skills load via ``--plugin-dir`` and
      host skills follow the default sources.

    ``--plugin-dir`` is emitted only when ``bundle_dir`` actually contains a
    ``skills/`` directory and host skills are enabled. ``skills: none`` uses
    ``--add-dir`` instead because ``--disable-slash-commands`` intentionally
    disables plugin Skill discovery too.

    :param bundle_dir: Materialized agent-bundle root, or ``None`` when
        the launch has no bundle (e.g. the ``omnigent claude`` CLI
        running against the user's own ``~/.claude`` config).
    :param agent_name: Agent display name for the plugin manifest, e.g.
        ``"researcher"``. ``None`` falls back to the bundle basename.
    :param skills_filter: The spec's ``skills_filter``: ``"all"`` /
        ``"none"`` / a list of skill names. Defaults to ``"all"``.
    :returns: CLI args to append after ``claude`` (possibly empty).
    """
    args: list[str] = []
    has_bundle_skills = bundle_dir is not None and (bundle_dir / "skills").is_dir()
    if skills_filter == "none":
        # Claude Code couples OAuth to the user setting source: an empty
        # --setting-sources value reports "Not logged in" even when the host
        # CLI is authenticated. Keep only the user source, then independently
        # suppress every slash-command Skill and ambient MCP server.
        args.extend(
            [
                "--setting-sources",
                "user",
                "--disable-slash-commands",
                "--strict-mcp-config",
            ]
        )
        if has_bundle_skills:
            args.extend(["--add-dir", str(bundle_dir)])
        return args
    if has_bundle_skills:
        assert bundle_dir is not None
        ensure_bundle_plugin_manifest(bundle_dir, agent_name)
        args.extend(["--plugin-dir", str(bundle_dir)])
    return args


def claude_native_skill_prompt(
    bundle_dir: Path | None,
    *,
    skills_filter: str | list[str] = "all",
) -> str | None:
    """Return the on-demand Bundle Skill index for native ``skills: none``.

    Claude Code has no flag that loads OAuth while excluding only user Skills:
    OAuth and user configuration share the ``user`` setting source. Native
    therefore disables every slash-command Skill and gives the model a small
    index of its own Bundle Skill files. The model reads a selected
    ``SKILL.md`` only when needed, preserving progressive disclosure without
    inheriting ``~/.claude/skills``.

    :param bundle_dir: Materialized Agent Bundle root.
    :param skills_filter: The AgentSpec Skill filter.
    :returns: System-prompt fragment, or ``None`` outside ``skills: none`` or
        when the bundle contains no Skill files.
    """
    if skills_filter != "none" or bundle_dir is None:
        return None
    skills_root = bundle_dir / "skills"
    if not skills_root.is_dir():
        return None
    skill_files = sorted(path for path in skills_root.glob("*/SKILL.md") if path.is_file())
    if not skill_files:
        return None
    entries = "\n".join(f"- {path.parent.name}: {path}" for path in skill_files)
    return (
        "Ominigent Bundle Skill isolation is active. Host, user, and project "
        "slash-command Skills are disabled. The only role Skills available to "
        "you are listed below as local instruction files. Before using one, "
        "read its SKILL.md completely with the Read tool and resolve relative "
        "references from that Skill directory. Do not discover or load Skills "
        "outside this list.\n"
        f"{entries}"
    )
