"""Integration: the interim identity-linking rule and the guards behind it.

foundations-hardening R4.1-R4.5 (FH9-FH11), ADR-0103 decision 8. A sign-in
reaches an existing user through its own `(issuer, subject)`, through
`users.subject` for the dev issuer only, or through a verified email of a user
who never signed in and is neither an operator nor support staff. Whatever else
matches is refused, and nothing is written. Below the application, PostgreSQL
keeps a login identity of an operator to `dw_provisioner` and keeps every login
identity from being deleted by the application.

Each test makes its own people with fresh emails and subjects: one database
serves the whole session, and an email another test linked would read as "has
signed in" here.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_kernel.errors import PermissionDeniedError
from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.identity_provisioning import SqlIdentityBootstrap
from dw_platform.adapters.persistence.membership_lookup import SqlMembershipLookup
from dw_platform.adapters.persistence.separation_of_duties import refusal
from dw_platform.testing.seed_env import seed_test_env

pytestmark = pytest.mark.integration

DEFAULT_TENANT = uuid.UUID("d6b43d0e-c3c6-5dbc-bc08-150621bd9a5d")
DEFAULT_WORKSPACE = uuid.UUID("64764894-718d-5558-ba17-9a2949214063")
IDP = "https://issuer.test/realms/dw"
OTHER_IDP = "https://other-idp.test"


@dataclass(frozen=True)
class _Identity:
    subject: str
    email: str | None
    email_verified: bool
    issuer: str = IDP
    name: str | None = None
    auth_methods: frozenset[str] = frozenset()
    acr: str | None = None


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    await seed_test_env(db_urls.migrator)
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def admin(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    """The superuser on this test database, to act as another role with SET ROLE."""
    database = db_urls.migrator.rpartition("/")[2]
    engine = create_async_engine(
        f"{db_urls.admin.rpartition('/')[0]}/{database}", poolclass=NullPool
    )
    yield engine
    await engine.dispose()


def _bootstrap(engine: AsyncEngine) -> SqlIdentityBootstrap:
    return SqlIdentityBootstrap(
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        default_tenant_id=DEFAULT_TENANT,
        default_workspace_id=DEFAULT_WORKSPACE,
    )


def _email() -> str:
    return f"person-{uuid.uuid4().hex[:10]}@linking.test"


async def _user(
    migrator: AsyncEngine, *, email: str | None, subject: str | None = None
) -> uuid.UUID:
    """A person an importer or an invitation wrote: a row, and no sign-in."""
    user_id = uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.insert(tables.users).values(
                id=user_id,
                subject=subject or f"invite:{uuid.uuid4()}",
                email=email,
                display_name="Someone",
            )
        )
    return user_id


async def _identities(migrator: AsyncEngine, user_id: uuid.UUID) -> list[str]:
    async with migrator.connect() as conn:
        rows = await conn.scalars(
            sa.select(tables.external_identities.c.issuer).where(
                tables.external_identities.c.user_id == user_id
            )
        )
        return sorted(rows.all())


async def _refused(
    app_engine: AsyncEngine, identity: _Identity, reason_code: str
) -> PermissionDeniedError:
    with pytest.raises(PermissionDeniedError) as refused:
        await _bootstrap(app_engine).bootstrap(identity)
    assert refused.value.details["reason_code"] == reason_code
    return refused.value


# ---- R4.1, R4.2 (FH9) ----------------------------------------------------------


async def test_an_unverified_email_does_not_claim_an_invited_person(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R4.1: the invited person's email, unverified, is not the invited person."""
    email = _email()
    invited = await _user(migrator, email=email)

    await _refused(
        app_engine,
        _Identity(subject=f"kc-{uuid.uuid4()}", email=email, email_verified=False),
        "identity_email_in_use",
    )

    assert await _identities(migrator, invited) == []


async def test_a_verified_email_claims_a_person_who_never_signed_in(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """The positive half of R4.1/R4.2, so the refusals above prove something."""
    email = _email()
    invited = await _user(migrator, email=email)

    view = await _bootstrap(app_engine).bootstrap(
        _Identity(subject=f"kc-{uuid.uuid4()}", email=email.upper(), email_verified=True)
    )

    assert view.principal_id == invited
    assert await _identities(migrator, invited) == [IDP]


async def test_a_verified_email_does_not_claim_someone_who_has_signed_in(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R4.2: a second IdP asserting the same verified email is not let in."""
    email = _email()
    first = await _bootstrap(app_engine).bootstrap(
        _Identity(subject=f"kc-{uuid.uuid4()}", email=email, email_verified=True)
    )

    await _refused(
        app_engine,
        _Identity(
            subject=f"other-{uuid.uuid4()}", email=email, email_verified=True, issuer=OTHER_IDP
        ),
        "identity_email_in_use",
    )

    assert await _identities(migrator, first.principal_id) == [IDP]


@pytest.mark.parametrize("allowlist", ["platform_operators", "support_staff"])
async def test_a_verified_email_does_not_claim_an_operator_or_support_staff(
    app_engine: AsyncEngine, migrator: AsyncEngine, allowlist: str
) -> None:
    """R4.2: operator authority is never reached by an email, even one that
    never signed in."""
    email = _email()
    privileged = await _user(migrator, email=email)
    async with migrator.begin() as conn:
        if allowlist == "platform_operators":
            await conn.execute(
                sa.insert(tables.platform_operators).values(
                    user_id=privileged, note="test", created_by=privileged
                )
            )
        else:
            await conn.execute(
                sa.insert(tables.support_staff).values(
                    user_id=privileged, note="test", added_by=privileged
                )
            )

    await _refused(
        app_engine,
        _Identity(subject=f"kc-{uuid.uuid4()}", email=email, email_verified=True),
        "identity_email_in_use",
    )

    assert await _identities(migrator, privileged) == []


async def test_two_first_sign_ins_to_one_invited_person_link_only_one(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """Both would pass "never signed in" if each read before the other wrote."""
    email = _email()
    invited = await _user(migrator, email=email)
    attempts = [
        _Identity(subject=f"kc-{uuid.uuid4()}", email=email, email_verified=True),
        _Identity(
            subject=f"other-{uuid.uuid4()}", email=email, email_verified=True, issuer=OTHER_IDP
        ),
    ]

    outcomes = await asyncio.gather(
        *(_bootstrap(app_engine).bootstrap(attempt) for attempt in attempts),
        return_exceptions=True,
    )

    assert sum(not isinstance(o, BaseException) for o in outcomes) == 1, outcomes
    assert sum(isinstance(o, PermissionDeniedError) for o in outcomes) == 1, outcomes
    assert len(await _identities(migrator, invited)) == 1


# ---- R4.3 (FH10) ---------------------------------------------------------------


async def test_a_subject_of_another_issuer_reaches_no_user(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R4.3: a user known by `users.subject` alone is not reached by a token of
    another issuer whose `sub` happens to be that subject, neither by sign-in
    (where the new-user insert used to read the existing user back) nor by the
    per-request lookup."""
    subject = f"legacy-{uuid.uuid4()}"
    known = await _user(migrator, email=_email(), subject=subject)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.insert(tables.memberships).values(
                id=uuid.uuid4(),
                tenant_id=DEFAULT_TENANT,
                workspace_id=DEFAULT_WORKSPACE,
                user_id=known,
                role_keys=["member"],
            )
        )

    await _refused(
        app_engine,
        _Identity(subject=subject, email=_email(), email_verified=True, issuer=OTHER_IDP),
        "identity_subject_in_use",
    )

    lookup = SqlMembershipLookup(async_sessionmaker(app_engine, expire_on_commit=False))
    assert await lookup.find_access(subject, OTHER_IDP, DEFAULT_TENANT, DEFAULT_WORKSPACE) is None
    assert await _identities(migrator, known) == []
    # The dev issuer keeps resolving a user by the subject it stores.
    assert await lookup.find_access(subject, "dw-dev", DEFAULT_TENANT, DEFAULT_WORKSPACE)


# ---- R4.5 (FH9) ----------------------------------------------------------------


async def test_an_unverified_email_is_not_kept_on_a_new_user(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R4.5: otherwise the address is taken before its owner is invited, and the
    invitation (which reuses whoever holds the email) lands on this user."""
    email = _email()

    view = await _bootstrap(app_engine).bootstrap(
        _Identity(subject=f"kc-{uuid.uuid4()}", email=email, email_verified=False)
    )

    async with migrator.connect() as conn:
        stored = await conn.scalar(
            sa.select(tables.users.c.email).where(tables.users.c.id == view.principal_id)
        )
        holders = await conn.scalar(
            sa.select(sa.func.count())
            .select_from(tables.users)
            .where(sa.func.lower(tables.users.c.email) == email)
        )
    assert stored is None
    assert holders == 0, "an invitation of this email would reuse the squatter"


# ---- R4.4 (FH11): the database --------------------------------------------------


async def _operator(migrator: AsyncEngine) -> uuid.UUID:
    operator = await _user(migrator, email=_email())
    async with migrator.begin() as conn:
        await conn.execute(
            sa.insert(tables.platform_operators).values(
                user_id=operator, note="test", created_by=operator
            )
        )
    return operator


def _login_row(user_id: uuid.UUID, provider: str = "oidc") -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "issuer": IDP if provider != "zalo" else "zalo",
        "subject": f"s-{uuid.uuid4()}",
        "provider": provider,
    }


async def _constraint_of(engine: AsyncEngine, statement: sa.Executable) -> str:
    with pytest.raises(IntegrityError) as refused:
        async with engine.begin() as conn:
            await conn.execute(statement)
    return (refusal(refused.value) or ("",))[0]


@pytest.mark.parametrize("role", ["app", "migrator"])
async def test_only_the_provisioner_adds_an_operators_login_identity(
    app_engine: AsyncEngine, migrator: AsyncEngine, role: str
) -> None:
    """R4.4: `dw_app`, and the migrator too though it bypasses RLS: the trigger
    names `dw_provisioner`, not "a powerful role" (ADR-0103 decision 8)."""
    operator = await _operator(migrator)
    engine = app_engine if role == "app" else migrator

    constraint = await _constraint_of(
        engine, sa.insert(tables.external_identities).values(**_login_row(operator))
    )

    assert constraint == "ck_external_identities_privileged_relink"
    assert await _identities(migrator, operator) == []


async def test_the_provisioner_may_add_an_operators_login_identity(
    migrator: AsyncEngine, admin: AsyncEngine
) -> None:
    """The positive half. `dw_provisioner` holds no INSERT on the table today
    (no flow of it adds one yet), so the grant is given and taken back inside
    one rolled-back transaction: what is measured is the trigger alone."""
    operator = await _operator(migrator)
    async with admin.connect() as conn:
        transaction = await conn.begin()
        await conn.execute(
            sa.text("GRANT INSERT ON platform.external_identities TO dw_provisioner")
        )
        await conn.execute(sa.text("SET LOCAL ROLE dw_provisioner"))
        await conn.execute(sa.insert(tables.external_identities).values(**_login_row(operator)))
        await conn.execute(sa.text("RESET ROLE"))
        linked = await conn.scalar(
            sa.select(sa.func.count())
            .select_from(tables.external_identities)
            .where(tables.external_identities.c.user_id == operator)
        )
        await transaction.rollback()

    assert linked == 1


async def test_a_chat_link_of_an_operator_is_not_a_login_identity(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """Linking Zalo is where to send, not who signs in; the guard leaves it be."""
    operator = await _operator(migrator)
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.insert(tables.external_identities).values(**_login_row(operator, "zalo"))
        )

    assert await _identities(migrator, operator) == ["zalo"]


async def test_the_application_keeps_a_login_identity_and_may_drop_a_chat_link(
    app_engine: AsyncEngine, migrator: AsyncEngine
) -> None:
    """R4.4: no UPDATE at all, no DELETE of a login identity, a chat link deletable."""
    person = await _user(migrator, email=_email())
    login, chat = _login_row(person), _login_row(person, "zalo")
    async with migrator.begin() as conn:
        await conn.execute(sa.insert(tables.external_identities), [login, chat])
    identities = tables.external_identities.c

    with pytest.raises(ProgrammingError, match="permission denied"):
        async with app_engine.begin() as conn:
            await conn.execute(
                sa.update(tables.external_identities)
                .where(identities.id == login["id"])
                .values(user_id=uuid.uuid4())
            )
    constraint = await _constraint_of(
        app_engine, sa.delete(tables.external_identities).where(identities.id == login["id"])
    )
    async with app_engine.begin() as conn:
        await conn.execute(sa.delete(tables.external_identities).where(identities.id == chat["id"]))

    assert constraint == "ck_external_identities_login_kept"
    assert await _identities(migrator, person) == [IDP]


async def test_a_user_deleted_by_the_owner_takes_its_login_identities_along(
    migrator: AsyncEngine,
) -> None:
    """The delete cascading from `platform.users` runs as the table owner, which
    bypasses RLS, so the kept-identity guard lets it through."""
    person = await _user(migrator, email=_email())
    async with migrator.begin() as conn:
        await conn.execute(sa.insert(tables.external_identities).values(**_login_row(person)))
        await conn.execute(sa.delete(tables.users).where(tables.users.c.id == person))

    assert await _identities(migrator, person) == []


async def test_both_guards_name_the_chat_providers_the_code_names(migrator: AsyncEngine) -> None:
    """One list of chat providers: `tables.CHANNEL_LINK_PROVIDERS`. Read from the
    catalog, so a provider added to the code and not to the guards goes red."""
    async with migrator.connect() as conn:
        bodies = (
            await conn.scalars(
                sa.text(
                    "SELECT pg_get_functiondef(p.oid) FROM pg_proc p"
                    " JOIN pg_namespace n ON n.oid = p.pronamespace"
                    " WHERE n.nspname = 'platform'"
                    " AND p.proname IN"
                    " ('guard_privileged_login_identity', 'guard_login_identity_kept')"
                )
            )
        ).all()

    assert len(bodies) == 2
    for body in bodies:
        [listed] = re.findall(r"ARRAY\[([^\]]*)\]", body)
        assert set(re.findall(r"'([^']+)'", listed)) == set(tables.CHANNEL_LINK_PROVIDERS)
