"""SQLAlchemy-backed agent store."""

from __future__ import annotations

import builtins
import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from threading import RLock
from typing import ClassVar, cast

from sqlalchemy import and_, asc, desc, or_, select, text
from sqlalchemy import update as sql_update
from sqlalchemy.engine import Connection, CursorResult, Dialect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from omnigent.db.converters import sql_agent_to_entity
from omnigent.db.db_models import (
    SqlAgent,
    SqlConversation,
    current_workspace_id,
)
from omnigent.db.enum_codecs import encode_agent_kind
from omnigent.db.utils import (
    get_or_create_conversation_engine,
    get_or_create_engine,
    make_managed_session_maker,
    now_epoch,
)
from omnigent.entities import Agent, PagedList
from omnigent.stores.agent_store import AgentStore, AgentVersionConflict


@dataclass(eq=False)
class _TemplateCleanupTarget:
    driver_connection: object
    reset_failures: list[BaseException]
    termination_failures: list[BaseException]


@dataclass
class _TemplateCleanupDispatcher:
    dialect: Dialect
    original_rollback: Callable[[object], None]
    original_terminate: Callable[[object], None]
    previous_rollback: object | None
    previous_terminate: object | None
    targets: list[_TemplateCleanupTarget] = field(default_factory=list)


class SqlAlchemyAgentStore(AgentStore):
    """
    SQLAlchemy-backed implementation of :class:`AgentStore`.

    Persists agents in a relational database via SQLAlchemy ORM.
    """

    _template_termination_lock = RLock()
    _template_cleanup_dispatchers: ClassVar[dict[int, _TemplateCleanupDispatcher]] = {}

    def __init__(
        self, storage_location: str, conversation_storage_location: str | None = None
    ) -> None:
        """
        Initialize the SQLAlchemy agent store.

        Creates or reuses a SQLAlchemy engine and session factory
        for the given database URI.

        :param storage_location: SQLAlchemy database URI for the Omnigent DB,
            e.g. ``"sqlite:///agents.db"`` or
            ``"postgresql://user:pass@host/db"``.
        :param conversation_storage_location: Optional URI for the Agent
            Platform DB. The ``conversations`` table lives there, and
            resolving a session-scoped agent's ``session_id`` requires a
            reverse lookup on ``conversations.agent_id``. Defaults to
            ``storage_location`` when ``None`` (single-DB mode).
        """
        super().__init__(storage_location)
        self.conversation_storage_location = conversation_storage_location
        self._engine = get_or_create_engine(storage_location)
        self._session = make_managed_session_maker(self._engine)
        self._template_update_session = make_managed_session_maker(self._engine, immediate=True)
        conv_uri = conversation_storage_location or storage_location
        self._conv_engine = (
            self._engine
            if conv_uri == storage_location
            else get_or_create_conversation_engine(conv_uri)
        )
        self._conv_session = make_managed_session_maker(self._conv_engine)

    @staticmethod
    def _template_write_digest(workspace_id: int) -> bytes:
        value = f"omnigent:template-write:v1\0{workspace_id}".encode()
        return hashlib.sha256(value).digest()

    @classmethod
    def _template_write_lock_id(cls, workspace_id: int) -> int:
        return int.from_bytes(
            cls._template_write_digest(workspace_id)[:8],
            byteorder="big",
            signed=True,
        )

    @classmethod
    def _template_write_lock_name(cls, workspace_id: int) -> str:
        digest = cls._template_write_digest(workspace_id).hex()
        return f"omnigent:template-write:{digest[:40]}"

    @classmethod
    def _discard_failed_template_lock_connection(
        cls,
        connection: Connection,
        primary_error: BaseException,
        *,
        invalidate_first: bool = True,
    ) -> None:
        pool_connection = None
        driver_connection = None
        driver_access_error = None
        try:
            pool_connection = connection.connection
            driver_connection = pool_connection.driver_connection
        except BaseException as exc:  # noqa: BLE001
            driver_access_error = exc

        if invalidate_first:
            try:
                if driver_connection is None:
                    connection.invalidate()
                else:
                    cls._invalidate_template_lock_connection(
                        connection,
                        driver_connection,
                        primary_error,
                    )
                return
            except BaseException as exc:  # noqa: BLE001
                primary_error.add_note(f"Template lock connection invalidation failed: {exc!r}")

        if driver_access_error is not None:
            primary_error.add_note(
                f"Template lock driver connection access failed: {driver_access_error!r}"
            )

        try:
            connection.detach()
        except BaseException as exc:  # noqa: BLE001
            primary_error.add_note(f"Template lock connection detach failed: {exc!r}")

        if driver_connection is not None:
            try:
                driver_connection.close()
            except BaseException as exc:  # noqa: BLE001
                primary_error.add_note(f"Template lock driver close failed: {exc!r}")
            else:
                pool_connection.dbapi_connection = None

    @classmethod
    def _invalidate_template_lock_connection(
        cls,
        connection: Connection,
        driver_connection: object,
        primary_error: BaseException,
    ) -> None:
        reset_failures: list[BaseException] = []
        termination_failures: list[BaseException] = []
        try:
            with cls._observe_template_lock_driver_cleanup(
                connection,
                driver_connection,
                reset_failures,
                termination_failures,
            ):
                connection.invalidate()
        finally:
            cls._add_template_lock_driver_cleanup_notes(
                primary_error,
                reset_failures,
                termination_failures,
            )

    @staticmethod
    def _is_template_lock_driver(candidate: object, driver_connection: object) -> bool:
        if candidate is driver_connection:
            return True
        try:
            return candidate.driver_connection is driver_connection  # type: ignore[attr-defined]
        except BaseException:  # noqa: BLE001
            return False

    @classmethod
    @contextmanager
    def _observe_template_lock_driver_cleanup(
        cls,
        connection: Connection,
        driver_connection: object,
        reset_failures: list[BaseException],
        termination_failures: list[BaseException],
    ) -> Iterator[None]:
        dialect = connection.dialect
        target = _TemplateCleanupTarget(
            driver_connection,
            reset_failures,
            termination_failures,
        )
        with cls._template_termination_lock:
            dispatcher_key = id(dialect)
            dispatcher = cls._template_cleanup_dispatchers.get(dispatcher_key)
            if dispatcher is None:
                dispatcher = _TemplateCleanupDispatcher(
                    dialect=dialect,
                    original_rollback=dialect.do_rollback,
                    original_terminate=dialect.do_terminate,
                    previous_rollback=dialect.__dict__.get("do_rollback"),
                    previous_terminate=dialect.__dict__.get("do_terminate"),
                )

                def observable_rollback(candidate: object) -> None:
                    cls._dispatch_template_cleanup_rollback(dispatcher, candidate)

                def observable_terminate(candidate: object) -> None:
                    cls._dispatch_template_cleanup_terminate(dispatcher, candidate)

                dialect.do_rollback = observable_rollback
                dialect.do_terminate = observable_terminate
                cls._template_cleanup_dispatchers[dispatcher_key] = dispatcher
            else:
                assert dispatcher.dialect is dialect
            dispatcher.targets.append(target)

        try:
            yield
        finally:
            try:
                with cls._template_termination_lock:
                    dispatcher.targets.remove(target)
                    if not dispatcher.targets:
                        if dispatcher.previous_rollback is None:
                            del dialect.do_rollback
                        else:
                            dialect.do_rollback = dispatcher.previous_rollback
                        if dispatcher.previous_terminate is None:
                            del dialect.do_terminate
                        else:
                            dialect.do_terminate = dispatcher.previous_terminate
                        del cls._template_cleanup_dispatchers[dispatcher_key]
            finally:
                if len(termination_failures) >= 2:
                    try:
                        dispatcher.original_terminate(driver_connection)
                    except BaseException as exc:  # noqa: BLE001
                        termination_failures.append(exc)

    @classmethod
    def _template_cleanup_target(
        cls,
        dispatcher: _TemplateCleanupDispatcher,
        candidate: object,
    ) -> _TemplateCleanupTarget | None:
        with cls._template_termination_lock:
            return next(
                (
                    target
                    for target in reversed(dispatcher.targets)
                    if cls._is_template_lock_driver(candidate, target.driver_connection)
                ),
                None,
            )

    @classmethod
    def _dispatch_template_cleanup_rollback(
        cls,
        dispatcher: _TemplateCleanupDispatcher,
        candidate: object,
    ) -> None:
        target = cls._template_cleanup_target(dispatcher, candidate)
        if target is None:
            dispatcher.original_rollback(candidate)
            return
        try:
            dispatcher.original_rollback(candidate)
        except BaseException as exc:
            target.reset_failures.append(exc)
            raise

    @classmethod
    def _dispatch_template_cleanup_terminate(
        cls,
        dispatcher: _TemplateCleanupDispatcher,
        candidate: object,
    ) -> None:
        target = cls._template_cleanup_target(dispatcher, candidate)
        if target is None:
            dispatcher.original_terminate(candidate)
            return
        try:
            dispatcher.original_terminate(candidate)
        except BaseException as exc:  # noqa: BLE001
            target.termination_failures.append(exc)
            try:
                dispatcher.original_terminate(candidate)
            except BaseException as retry_exc:
                target.termination_failures.append(retry_exc)
                raise

    @staticmethod
    def _add_template_lock_driver_cleanup_notes(
        primary_error: BaseException,
        reset_failures: list[BaseException],
        termination_failures: list[BaseException],
    ) -> None:
        for failure in reset_failures:
            primary_error.add_note(f"Template lock driver reset failed: {failure!r}")
        for index, failure in enumerate(termination_failures):
            phase = "" if index == 0 else " retry" if index == 1 else " fallback"
            primary_error.add_note(f"Template lock driver termination{phase} failed: {failure!r}")

    @contextmanager
    def _template_lock_connection(self) -> Iterator[Connection]:
        connection_context = self._engine.connect()
        connection = connection_context.__enter__()
        try:
            driver_connection = connection.connection.driver_connection
        except BaseException:  # noqa: BLE001
            driver_connection = None
        primary_error: BaseException | None = None
        reset_failures: list[BaseException] = []
        termination_failures: list[BaseException] = []
        cleanup_error = None
        try:
            observation = (
                nullcontext()
                if driver_connection is None
                else self._observe_template_lock_driver_cleanup(
                    connection,
                    driver_connection,
                    reset_failures,
                    termination_failures,
                )
            )
            with observation:
                try:
                    yield connection
                except BaseException as exc:  # noqa: BLE001
                    primary_error = exc

                exit_arguments = (
                    type(primary_error) if primary_error is not None else None,
                    primary_error,
                    primary_error.__traceback__ if primary_error is not None else None,
                )
                suppressed = connection_context.__exit__(*exit_arguments)
                if primary_error is not None and suppressed:
                    primary_error = None
        except BaseException as exc:  # noqa: BLE001
            cleanup_error = exc
            if primary_error is None:
                primary_error = RuntimeError("Could not clean up the template lock connection")
            primary_error.add_note(f"Template lock connection cleanup failed: {exc!r}")
            self._discard_failed_template_lock_connection(
                connection,
                primary_error,
                invalidate_first=False,
            )

        if reset_failures or termination_failures:
            if primary_error is None:
                primary_error = RuntimeError("Could not clean up the template lock connection")
            self._add_template_lock_driver_cleanup_notes(
                primary_error,
                reset_failures,
                termination_failures,
            )

        if primary_error is not None:
            if cleanup_error is not None and primary_error is not cleanup_error:
                raise primary_error.with_traceback(primary_error.__traceback__) from cleanup_error
            raise primary_error.with_traceback(primary_error.__traceback__)

    @contextmanager
    def _template_write_session(self, workspace_id: int) -> Iterator[Session]:
        dialect = self._engine.dialect.name
        if dialect == "sqlite":
            with self._template_update_session() as session:
                yield session
            return

        if dialect == "postgresql":
            with self._session() as session:
                session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_id)"),
                    {"lock_id": self._template_write_lock_id(workspace_id)},
                )
                yield session
            return

        if dialect not in {"mysql", "mariadb"}:
            raise RuntimeError(
                f"Template name locking is unsupported for database dialect {dialect!r}"
            )

        lock_name = self._template_write_lock_name(workspace_id)
        with self._template_lock_connection() as connection:
            try:
                acquired = connection.execute(
                    text("SELECT GET_LOCK(:lock_name, :timeout)"),
                    {"lock_name": lock_name, "timeout": 20},
                ).scalar_one()
            except BaseException as exc:
                self._discard_failed_template_lock_connection(connection, exc)
                raise
            if acquired != 1:
                connection.rollback()
                raise RuntimeError("Could not acquire the template name lock")

            transaction = None
            primary_error: BaseException | None = None
            try:
                connection.commit()
                transaction = connection.begin()
                with Session(bind=connection, expire_on_commit=False) as session:
                    yield session
                    session.flush()
                transaction.commit()
            except BaseException as exc:  # noqa: BLE001
                primary_error = exc

            if transaction is not None and transaction.is_active:
                try:
                    transaction.rollback()
                except BaseException as exc:  # noqa: BLE001
                    if primary_error is None:
                        primary_error = exc
                    else:
                        primary_error.add_note(f"Template transaction rollback failed: {exc!r}")

            release_error: BaseException | None = None
            cleanup_error: BaseException | None = None
            try:
                if connection.in_transaction():
                    connection.rollback()
                released = connection.execute(
                    text("SELECT RELEASE_LOCK(:lock_name)"),
                    {"lock_name": lock_name},
                ).scalar_one()
                if released != 1:
                    raise RuntimeError("Could not release the template name lock")
                connection.commit()
            except BaseException as exc:  # noqa: BLE001
                release_error = exc
                cleanup_error = primary_error or RuntimeError(
                    "Could not release the template name lock"
                )
                cleanup_error.add_note(f"Template lock cleanup failed: {release_error!r}")
                self._discard_failed_template_lock_connection(connection, cleanup_error)

            if primary_error is not None:
                raise primary_error.with_traceback(primary_error.__traceback__)
            if release_error is not None:
                assert cleanup_error is not None
                raise cleanup_error from release_error

    def _session_id_for_agent(self, agent_id: str) -> str | None:
        """
        Reverse-lookup the spawn-tree root bound to a session-scoped agent.

        ``conversations.agent_id`` is the sole link (the agent row carries no
        back-pointer), and the ``conversations`` table lives in the AP DB — so
        this must run on the conversation engine, not the Omnigent engine that
        owns the ``agents`` table.

        :param agent_id: Agent identifier, e.g. ``"ag_abc123"``.
        Multiple named child sessions can share the same session-scoped
        ``agent_id``. Selecting their common ``root_conversation_id`` keeps
        authorization stable regardless of which row the bounded lookup sees.

        :returns: Owning root conversation id, or ``None`` when no
            conversation points at this agent.
        """
        with self._conv_session() as conv_sess:
            return conv_sess.execute(
                select(SqlConversation.root_conversation_id)
                .where(
                    SqlConversation.workspace_id == current_workspace_id(),
                    SqlConversation.agent_id == agent_id,
                )
                .limit(1)
            ).scalar_one_or_none()

    def create(
        self,
        agent_id: str,
        name: str,
        bundle_location: str,
        description: str | None = None,
    ) -> Agent:
        """
        Register a new template agent in the database.

        :param agent_id: Pre-generated unique agent identifier,
            e.g. ``"ag_0f1a2b3c..."``.
        :param name: Human-readable agent name. Must be unique,
            e.g. ``"code-assistant"``.
        :param bundle_location: Artifact store key for the bundle,
            e.g. ``"ag_abc123/a1b2c3d4e5f6..."``.
        :param description: Optional free-text description.
        :returns: The newly created :class:`Agent`.
        """
        workspace_id = current_workspace_id()
        row = SqlAgent(
            workspace_id=workspace_id,
            id=agent_id,
            created_at=now_epoch(),
            name=name,
            bundle_location=bundle_location,
            version=1,
            kind=encode_agent_kind("template"),
            description=description,
        )
        with self._template_write_session(workspace_id) as session:
            # Template names are unique within a workspace. This can't be a
            # partial unique index (MySQL has none), so enforce it here.
            conflict = session.execute(
                select(SqlAgent.id).where(
                    SqlAgent.workspace_id == workspace_id,
                    SqlAgent.name == name,
                    SqlAgent.kind == encode_agent_kind("template"),
                )
            ).first()
            if conflict is not None:
                raise IntegrityError(
                    "Duplicate template agent name",
                    params={"name": name},
                    orig=Exception(f"UNIQUE constraint: name={name!r}"),
                )
            session.add(row)
            return sql_agent_to_entity(row)

    def get(self, agent_id: str) -> Agent | None:
        """
        Fetch an agent by its unique ID.

        :param agent_id: Unique agent identifier,
            e.g. ``"agent_abc123"``.
        :returns: The :class:`Agent` if found, otherwise ``None``.
        """
        with self._session() as session:
            row = session.get(SqlAgent, (current_workspace_id(), agent_id))
            if row is None:
                return None
        # For session-scoped agents, derive the owning conversation id
        # from the forward pointer so callers can use agent.session_id.
        # Runs outside the Omnigent session: the lookup targets the AP DB.
        session_id: str | None = None
        if row.kind == encode_agent_kind("session"):
            session_id = self._session_id_for_agent(agent_id)
        return sql_agent_to_entity(row, session_id=session_id)

    def get_by_name(self, name: str) -> Agent | None:
        """
        Look up a registered template agent by its unique name.

        Only agents with ``kind = 'template'`` are returned; session-scoped
        copies bound to a specific conversation are excluded.

        :param name: The template agent's unique name,
            e.g. ``"code-assistant"``.
        :returns: The :class:`Agent` if found, otherwise ``None``.
        """
        with self._session() as session:
            row = session.execute(
                select(SqlAgent).where(
                    SqlAgent.workspace_id == current_workspace_id(),
                    SqlAgent.name == name,
                    SqlAgent.kind == encode_agent_kind("template"),
                )
            ).scalar_one_or_none()
            return sql_agent_to_entity(row) if row else None

    def list(
        self,
        limit: int = 20,
        after: str | None = None,
        before: str | None = None,
        order: str = "desc",
    ) -> PagedList[Agent]:
        """
        List registered template agents with cursor-based pagination.

        Only agents with ``kind = 'template'`` are returned; session-scoped
        copies are excluded.

        :param limit: Maximum number of agents to return.
        :param after: Cursor agent ID; return agents appearing
            after this agent in sort order,
            e.g. ``"agent_abc123"``.
        :param before: Cursor agent ID; return agents appearing
            before this agent in sort order.
        :param order: Sort direction, ``"desc"`` or ``"asc"``.
        :returns: A :class:`PagedList` of :class:`Agent` objects.
        """
        with self._session() as session:
            is_desc = order == "desc"
            sort_fn = desc if is_desc else asc
            is_template = SqlAgent.kind == encode_agent_kind("template")
            in_workspace = SqlAgent.workspace_id == current_workspace_id()
            stmt = select(SqlAgent).where(in_workspace, is_template)
            if after:
                sub = (
                    select(SqlAgent.created_at)
                    .where(in_workspace, SqlAgent.id == after, is_template)
                    .scalar_subquery()
                )
                ts_cmp = SqlAgent.created_at < sub if is_desc else SqlAgent.created_at > sub
                id_cmp = SqlAgent.id < after if is_desc else SqlAgent.id > after
                stmt = stmt.where(or_(ts_cmp, and_(SqlAgent.created_at == sub, id_cmp)))
            if before:
                sub = (
                    select(SqlAgent.created_at)
                    .where(in_workspace, SqlAgent.id == before, is_template)
                    .scalar_subquery()
                )
                ts_cmp = SqlAgent.created_at > sub if is_desc else SqlAgent.created_at < sub
                id_cmp = SqlAgent.id > before if is_desc else SqlAgent.id < before
                stmt = stmt.where(or_(ts_cmp, and_(SqlAgent.created_at == sub, id_cmp)))
            stmt = stmt.order_by(sort_fn(SqlAgent.created_at), sort_fn(SqlAgent.id)).limit(
                limit + 1
            )
            rows = list(session.execute(stmt).scalars().all())
            has_more = len(rows) > limit
            if has_more:
                rows = rows[:limit]
            entities = [sql_agent_to_entity(r) for r in rows]
            return PagedList(
                data=entities,
                first_id=entities[0].id if entities else None,
                last_id=entities[-1].id if entities else None,
                has_more=has_more,
            )

    def get_names(self, agent_ids: builtins.list[str]) -> dict[str, str]:
        """
        Batch-fetch agent names for a list of IDs.

        Uses a single SQL ``IN`` query. IDs not found in the store
        are omitted from the result.

        :param agent_ids: List of agent identifiers to look up,
            e.g. ``["ag_abc123", "ag_def456"]``.
        :returns: Mapping of ``{agent_id: agent_name}`` for found
            agents.
        """
        if not agent_ids:
            return {}
        with self._session() as session:
            rows = session.execute(
                select(SqlAgent.id, SqlAgent.name).where(
                    SqlAgent.workspace_id == current_workspace_id(),
                    SqlAgent.id.in_(agent_ids),
                )
            ).all()
            return {row.id: row.name for row in rows}

    def update(
        self,
        agent_id: str,
        bundle_location: str,
    ) -> Agent | None:
        """
        Update an agent's bundle location, bump version, and set
        ``updated_at``.

        :param agent_id: Unique agent identifier,
            e.g. ``"agent_abc123"``.
        :param bundle_location: New artifact store key for the
            bundle, e.g. ``"ag_abc123/a1b2c3d4e5f6..."``.
        :returns: The updated :class:`Agent`, or ``None`` if not
            found.
        """
        workspace_id = current_workspace_id()
        with self._session() as session:
            result = cast(
                CursorResult[tuple[object]],
                session.execute(
                    sql_update(SqlAgent)
                    .where(
                        SqlAgent.workspace_id == workspace_id,
                        SqlAgent.id == agent_id,
                    )
                    .values(
                        bundle_location=bundle_location,
                        version=SqlAgent.version + 1,
                        updated_at=now_epoch(),
                    )
                ),
            )
            if result.rowcount != 1:
                return None
            row = session.get(SqlAgent, (workspace_id, agent_id))
            assert row is not None
        # Reverse lookup targets the AP DB — see _session_id_for_agent.
        session_id: str | None = None
        if row.kind == encode_agent_kind("session"):
            session_id = self._session_id_for_agent(agent_id)
        return sql_agent_to_entity(row, session_id=session_id)

    def update_template(
        self,
        agent_id: str,
        bundle_location: str,
        name: str,
        description: str | None,
        expected_version: int,
    ) -> Agent | None:
        """Atomically update a template if its version is unchanged."""
        workspace_id = current_workspace_id()
        template_kind = encode_agent_kind("template")
        with self._template_write_session(workspace_id) as session:
            current = session.execute(
                select(SqlAgent.kind, SqlAgent.version)
                .where(
                    SqlAgent.workspace_id == workspace_id,
                    SqlAgent.id == agent_id,
                )
                .with_for_update()
            ).one_or_none()
            if current is None:
                return None
            if current.kind != template_kind:
                raise ValueError(f"Agent {agent_id!r} is not a template agent")
            if current.version != expected_version:
                raise AgentVersionConflict(agent_id, expected_version, current.version)

            conflict = session.execute(
                select(SqlAgent.id).where(
                    SqlAgent.workspace_id == workspace_id,
                    SqlAgent.name == name,
                    SqlAgent.kind == template_kind,
                    SqlAgent.id != agent_id,
                )
            ).first()
            if conflict is not None:
                raise IntegrityError(
                    "Duplicate template agent name",
                    params={"name": name},
                    orig=Exception(f"UNIQUE constraint: name={name!r}"),
                )

            result = cast(
                CursorResult[tuple[object]],
                session.execute(
                    sql_update(SqlAgent)
                    .where(
                        SqlAgent.workspace_id == workspace_id,
                        SqlAgent.id == agent_id,
                        SqlAgent.kind == template_kind,
                        SqlAgent.version == expected_version,
                    )
                    .values(
                        name=name,
                        description=description,
                        bundle_location=bundle_location,
                        version=SqlAgent.version + 1,
                        updated_at=now_epoch(),
                    )
                ),
            )
            if result.rowcount != 1:
                actual = session.execute(
                    select(SqlAgent.kind, SqlAgent.version)
                    .where(
                        SqlAgent.workspace_id == workspace_id,
                        SqlAgent.id == agent_id,
                    )
                    .with_for_update()
                ).one_or_none()
                if actual is None:
                    return None
                if actual.kind != template_kind:
                    raise ValueError(f"Agent {agent_id!r} is not a template agent")
                raise AgentVersionConflict(agent_id, expected_version, actual.version)

            row = session.get(SqlAgent, (workspace_id, agent_id))
            assert row is not None
            return sql_agent_to_entity(row)

    def delete(self, agent_id: str) -> bool:
        """
        Delete an agent by ID.

        :param agent_id: Unique agent identifier,
            e.g. ``"agent_abc123"``.
        :returns: ``True`` if the agent was deleted, ``False`` if
            it did not exist.
        """
        with self._session() as session:
            row = session.get(SqlAgent, (current_workspace_id(), agent_id))
            if not row:
                return False
            session.delete(row)
            return True
