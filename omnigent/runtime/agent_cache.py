"""Two-tier agent cache — disk + in-memory — backed by ArtifactStore."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path

from omnigent.entities import LoadedAgent
from omnigent.spec import AgentSpec
from omnigent.spec import load as load_spec
from omnigent.stores.artifact_store import ArtifactStore

CacheKey = tuple[str, str, bool]

_logger = logging.getLogger(__name__)


def _bundle_digest(bundle_location: str) -> str:
    """Return a stable directory-safe identity for one bundle location."""
    digest = bundle_location.rsplit("/", 1)[-1]
    if len(digest) == 64 and all(char in "0123456789abcdefABCDEF" for char in digest):
        return digest.lower()
    return hashlib.sha256(bundle_location.encode()).hexdigest()


def _cleanup_tree_best_effort(path: Path, *, purpose: str) -> None:
    """Remove a committed swap's obsolete tree without changing its result."""
    for attempt in range(2):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == 1:
                _logger.warning("Failed to clean %s at %s", purpose, path, exc_info=True)


def _load_bundle_bytes(
    bundle_bytes: bytes,
    dest: Path,
    *,
    expand_env: bool,
) -> AgentSpec:
    """Write, parse, and best-effort clean one temporary bundle archive."""
    tmp_fd: int | None = None
    tmp_path: Path | None = None
    try:
        tmp_fd, tmp_name = tempfile.mkstemp(suffix=".tar.gz")
        tmp_path = Path(tmp_name)
        os.close(tmp_fd)
        tmp_fd = None
        tmp_path.write_bytes(bundle_bytes)
        return load_spec(
            tmp_path,
            dest=dest,
            expand_env=expand_env,
            prune_invalid_sub_agents=True,
        )
    finally:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                _logger.warning("Failed to close temporary agent bundle", exc_info=True)
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                try:
                    os.unlink(tmp_path)
                except FileNotFoundError:
                    pass
                except OSError:
                    _logger.warning(
                        "Failed to remove temporary agent bundle at %s",
                        tmp_path,
                        exc_info=True,
                    )


class AgentCache:
    """
    Two-tier cache for loaded agents.

    Tier 1 (in-memory): parsed AgentSpec objects keyed by agent, Digest,
    and environment-expansion mode.
    Tier 2 (disk): extracted directories under
    cache_dir/<agent_id>/<digest>/expand-env-{0|1}/.
    Source of truth: ArtifactStore (tarball bytes).

    On cache miss the bundle is downloaded from the ArtifactStore,
    extracted to disk, parsed, validated, and stored in both tiers.

    This is an **execution** load path, so it loads with
    ``prune_invalid_sub_agents=True``: a sub-agent that fails
    validation here means this server is older than whatever produced
    the bundle and can't run that sub-agent (version skew), so it is
    dropped (with a WARNING) and the parent agent still dispatches.
    Authoring/upload validation stays strict elsewhere
    (:func:`omnigent.server.bundles.validate_agent_bundle`). See
    :func:`omnigent.spec.load`.
    """

    def __init__(self, artifact_store: ArtifactStore, cache_dir: Path) -> None:
        """
        Initialize the two-tier agent cache.

        :param artifact_store: The ArtifactStore holding agent
            bundle tarballs (source of truth).
        :param cache_dir: Root directory for the disk cache.
            Each bundle variant is extracted below
            ``<cache_dir>/<agent_id>/<digest>/``.
        """
        self._artifact_store = artifact_store
        self._cache_dir = cache_dir
        self._specs: dict[CacheKey, AgentSpec] = {}
        self._lock = threading.RLock()

    def load(
        self,
        agent_id: str,
        bundle_location: str,
        *,
        expand_env: bool = False,
    ) -> LoadedAgent:
        """
        Load an agent, populating caches on miss.

        Raises KeyError if the agent bundle does not exist in the
        ArtifactStore. Raises ValueError if the spec is invalid.

        :param agent_id: Unique agent identifier,
            e.g. ``"ag_abc123"``.
        :param bundle_location: Artifact store key for the bundle,
            e.g. ``"ag_abc123/a1b2c3d4e5f6..."``.
        :param expand_env: Whether to expand ``${VAR}`` references in
            the spec against the server process environment. Defaults
            to ``False`` and MUST stay ``False`` for tenant-supplied
            (session-scoped) agents: expanding their ``${VAR}``
            against the server env leaks secrets into a spec-controlled
            MCP/LLM connection. Callers pass
            ``expand_env=True`` only for operator-authored template
            agents (``Agent.session_id is None`` — ``--agent`` /
            built-ins). The default is fail-safe: a caller that
            forgets the flag gets no expansion (a template agent may
            fail to resolve, loudly) rather than a silent leak.
        :returns: A LoadedAgent with the parsed spec and the
            on-disk working directory.
        """
        with self._lock:
            digest = _bundle_digest(bundle_location)
            key = (agent_id, digest, expand_env)
            workdir = self._workdir(key)

            # Tier 1: in-memory spec for this immutable bundle and parse mode.
            if key in self._specs:
                return LoadedAgent(spec=self._specs[key], workdir=workdir)

            # Tier 2: disk cache (directory already extracted)
            if workdir.is_dir():
                spec = load_spec(
                    workdir,
                    expand_env=expand_env,
                    prune_invalid_sub_agents=True,
                )
                self._specs[key] = spec
                return LoadedAgent(spec=spec, workdir=workdir)

            # Cache miss — download bundle, write to temp file, extract
            bundle_bytes = self._artifact_store.get(bundle_location)
            return self._extract_and_cache(
                key,
                bundle_bytes,
                workdir,
                expand_env=expand_env,
            )

    def replace(
        self,
        agent_id: str,
        bundle_location: str,
        bundle_bytes: bytes,
        *,
        expand_env: bool = False,
    ) -> LoadedAgent:
        """
        Warm-swap an agent's cached spec and disk directory.

        Extracts the new bundle to a temp directory, installs it at
        the cache location with rollback protection, then swaps the
        in-memory spec entry. Concurrent readers see either the old
        spec or the new spec, never an empty cache.

        :param agent_id: Unique agent identifier,
            e.g. ``"ag_abc123"``.
        :param bundle_location: New artifact store key (unused
            during extraction but passed for consistency),
            e.g. ``"ag_abc123/a1b2c3d4e5f6..."``.
        :param bundle_bytes: Raw bytes of the new ``.tar.gz``
            bundle.
        :param expand_env: Whether to expand ``${VAR}`` references
            against the server process environment. Defaults to
            ``False`` (fail-safe); pass ``True`` only for
            operator-authored template agents. See :meth:`load` for
            the full rationale.
        :returns: A LoadedAgent with the new spec and working
            directory.
        """
        with self._lock:
            digest = _bundle_digest(bundle_location)
            key = (agent_id, digest, expand_env)
            workdir = self._workdir(key)
            workdir.parent.mkdir(parents=True, exist_ok=True)
            staging_dir = Path(
                tempfile.mkdtemp(prefix=f".{workdir.name}-staging-", dir=workdir.parent)
            )

            # Everything through staging installation is pre-commit. Preserve
            # the old directory in a sibling backup and restore it on failure.
            backup_dir: Path | None = None
            old_moved = False
            try:
                # Parse and validate before touching the installed variant.
                spec = _load_bundle_bytes(
                    bundle_bytes,
                    staging_dir,
                    expand_env=expand_env,
                )
                if workdir.is_dir():
                    backup_dir = Path(
                        tempfile.mkdtemp(
                            prefix=f".{workdir.name}-backup-",
                            dir=workdir.parent,
                        )
                    )
                    backup_dir.rmdir()
                    workdir.rename(backup_dir)
                    old_moved = True
                staging_dir.rename(workdir)
            except BaseException as install_error:
                if old_moved and backup_dir is not None:
                    if workdir.exists():
                        shutil.rmtree(workdir, ignore_errors=True)
                    try:
                        backup_dir.rename(workdir)
                    except OSError as rename_error:
                        try:
                            os.replace(backup_dir, workdir)
                        except OSError as restore_error:
                            self._specs.pop(key, None)
                            shutil.rmtree(staging_dir, ignore_errors=True)
                            raise RuntimeError(
                                "Failed to install cache variant "
                                f"{workdir} ({install_error}) and restore its "
                                f"previous directory ({rename_error}; {restore_error}); "
                                f"recovery data remains at {backup_dir}"
                            ) from restore_error
                elif backup_dir is not None:
                    shutil.rmtree(backup_dir, ignore_errors=True)
                shutil.rmtree(staging_dir, ignore_errors=True)
                raise

            # Commit point: disk and memory now describe the same generation.
            # Backup cleanup is post-commit and must not turn success into an
            # exception; evict() also removes any residual sibling backup.
            self._specs[key] = spec
            if backup_dir is not None:
                _cleanup_tree_best_effort(backup_dir, purpose="agent cache backup")

            return LoadedAgent(spec=spec, workdir=workdir)

    def evict(self, agent_id: str) -> None:
        """
        Remove an agent from both cache tiers. Called when an
        agent is deleted. No-op if the agent is not cached.

        :param agent_id: Unique agent identifier,
            e.g. ``"ag_abc123"``.
        """
        with self._lock:
            for key in tuple(self._specs):
                if key[0] == agent_id:
                    self._specs.pop(key, None)
            agent_dir = self._cache_dir / agent_id
            if agent_dir.is_dir():
                shutil.rmtree(agent_dir)

    def _workdir(self, key: CacheKey) -> Path:
        """Return the isolated disk path for one cache identity."""
        agent_id, digest, expand_env = key
        return self._cache_dir / agent_id / digest / f"expand-env-{int(expand_env)}"

    def _extract_and_cache(
        self,
        key: CacheKey,
        bundle_bytes: bytes,
        workdir: Path,
        *,
        expand_env: bool = False,
    ) -> LoadedAgent:
        """
        Extract bundle bytes to disk and populate both cache tiers.

        :param key: Agent, bundle Digest, and environment-expansion identity.
        :param bundle_bytes: Raw bytes of the ``.tar.gz`` bundle.
        :param workdir: Target directory for extraction.
        :param expand_env: Whether to expand ``${VAR}`` references
            against the server process environment. Forwarded from
            :meth:`load`; defaults to ``False`` (fail-safe). See
            :meth:`load` for the rationale.
        :returns: A LoadedAgent with the parsed spec and workdir.
        """
        workdir.parent.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(
            tempfile.mkdtemp(prefix=f".{workdir.name}-staging-", dir=workdir.parent)
        )
        try:
            spec = _load_bundle_bytes(bundle_bytes, staging_dir, expand_env=expand_env)
            staging_dir.rename(workdir)
        except BaseException:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

        self._specs[key] = spec
        return LoadedAgent(spec=spec, workdir=workdir)
