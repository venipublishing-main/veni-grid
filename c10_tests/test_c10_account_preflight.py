"""Offline tests: these deliberately DO NOT implement or authenticate OAuth."""
from dataclasses import replace
from pathlib import Path
from time import time
from uuid import uuid4

import pytest

from veni_grid_authority.c9_server_bridge import ServerScheduleRegistration
from veni_grid_authority.c10_account_preflight import (
    AccountLink, AccountPreflightRejected, C10AccountPreflight, VerifierAssertion,
)

ISSUER = "https://id.synthetic.example/auth/v1"
AUDIENCE = "veni-grid-synthetic"
CREDENTIAL = "offline-synthetic-session-credential"


@pytest.fixture
def scenario():
    account = str(uuid4())
    session = str(uuid4())
    org_a, school_a = str(uuid4()), str(uuid4())
    org_b, school_b = str(uuid4()), str(uuid4())
    subject = "opaque-upstream-subject-412"
    now = int(time())
    registration = lambda key, org, sid: ServerScheduleRegistration(
        key=key, organisation_uuid=org, schedule_uuid=sid,
        c4_source_organisation_id="synthetic-org", c4_source_schedule_id="synthetic-options",
        c4_target_sha256="0" * 64,
    )
    registrations = {
        "school-a-options": registration("school-a-options", org_a, school_a),
        "school-b-options": registration("school-b-options", org_b, school_b),
    }
    state = {
        "tokens": {},
        "sessions": {session},
        "accounts": {account},
        "links": [AccountLink(issuer=ISSUER, subject=subject,
                              account_uuid=account, state="ACTIVE", verified=True)],
        "memberships": {(account, org_a)},
        "grants": {(account, org_a, school_a, "propose"),
                   (account, org_a, school_a, "approve")},
        "registered": registrations,
    }

    def gate(mode="SHARED_AUTH", **overrides):
        assert mode in ("SHARED_AUTH", "OAUTH_HANDOFF")
        state["tokens"][CREDENTIAL] = VerifierAssertion(
            transport=mode, issuer=ISSUER, audience=AUDIENCE,
            subject=account if mode == "SHARED_AUTH" else subject,
            session_id=session, assurance="aal2", issued_at=now - 60, expires_at=now + 600,
        )
        args = dict(
            approved_transport=mode, pinned_issuer=ISSUER, pinned_audience=AUDIENCE,
            trusted_verify=lambda credential, action: state["tokens"][credential],
            current_session=lambda issuer, sub, sid: sid in state["sessions"],
            current_account=lambda uid: uid in state["accounts"],
            verified_links=lambda issuer, sub: state["links"],
            current_membership=lambda uid, org: (uid, org) in state["memberships"],
            exact_schedule_grant=lambda uid, org, sid, action:
                (uid, org, sid, action) in state["grants"],
            registrations=registrations,
        )
        return C10AccountPreflight(**{**args, **overrides})

    def check(g, mode="SHARED_AUTH", action="propose", **changes):
        kwargs = dict(transport=mode, credential=CREDENTIAL,
                      schedule_key="school-a-options", action=action)
        return g.for_grid(**{**kwargs, **changes})

    return locals()


def denied(code, fn):
    with pytest.raises(AccountPreflightRejected) as exc:
        fn()
    assert exc.value.code == code


def test_neither_identity_candidate_is_enabled_by_default():
    g = C10AccountPreflight()
    denied("TRANSPORT_DECISION_PENDING", lambda: g.for_grid(
        transport="SHARED_AUTH", credential=CREDENTIAL,
        schedule_key="school-a-options", action="propose"))


@pytest.mark.parametrize("mode", ["SHARED_AUTH", "OAUTH_HANDOFF"])
def test_active_verified_session_and_exact_school_permission_preflight_only(scenario, mode):
    g = scenario["gate"](mode)
    result = scenario["check"](g, mode)
    assert result.account_uuid == scenario["account"]
    assert result.organisation_uuid == scenario["org_a"]
    assert result.schedule_uuid == scenario["school_a"]
    assert result.action == "propose" and result.assurance == "aal2"
    assert not hasattr(result, "published_revision")
    assert not hasattr(result, "role") and not hasattr(result, "email")


@pytest.mark.parametrize("mode", ["SHARED_AUTH", "OAUTH_HANDOFF"])
def test_approval_requires_current_aal2_not_a_plain_login(scenario, mode):
    g = scenario["gate"](mode)
    s = scenario["state"]
    s["tokens"][CREDENTIAL] = replace(s["tokens"][CREDENTIAL], assurance="aal1")
    assert scenario["check"](g, mode).action == "propose"
    denied("MFA_STEP_UP_REQUIRED", lambda: scenario["check"](g, mode, action="approve"))


@pytest.mark.parametrize("mode", ["SHARED_AUTH", "OAUTH_HANDOFF"])
def test_revoked_session_rejected_on_every_call(scenario, mode):
    g = scenario["gate"](mode)
    scenario["check"](g, mode)
    scenario["state"]["sessions"].clear()
    denied("SESSION_REVOKED_OR_MISSING", lambda: scenario["check"](g, mode))


@pytest.mark.parametrize("mode", ["SHARED_AUTH", "OAUTH_HANDOFF"])
def test_wrong_transport_and_unpinned_provider_denied(scenario, mode):
    g = scenario["gate"](mode)
    opposite = "OAUTH_HANDOFF" if mode == "SHARED_AUTH" else "SHARED_AUTH"
    denied("TRANSPORT_NOT_APPROVED", lambda: scenario["check"](g, opposite))
    s = scenario["state"]
    for kw in ({"issuer": "https://other.example/auth/v1"}, {"audience": "wrong-audience"},
               {"transport": opposite}):
        original = s["tokens"][CREDENTIAL]
        s["tokens"][CREDENTIAL] = replace(original, **kw)
        denied("UNPINNED_IDENTITY_PROVIDER", lambda: scenario["check"](g, mode))
        s["tokens"][CREDENTIAL] = original


@pytest.mark.parametrize("mode", ["SHARED_AUTH", "OAUTH_HANDOFF"])
def test_no_forged_browser_identity_or_client_selected_verifier(scenario, mode):
    g = scenario["gate"](mode)
    denied("INVALID_OPAQUE_CREDENTIAL", lambda: scenario["check"](
        g, mode, credential={"sub": scenario["account"], "role": "school_admin"}))
    denied("TRUSTED_VERIFIER_UNAVAILABLE_OR_DENIED", lambda: scenario["check"](
        g, mode, credential="forged-claims-from-user-metadata"))


@pytest.mark.parametrize("mode", ["SHARED_AUTH", "OAUTH_HANDOFF"])
def test_account_status_and_membership_and_schedule_grant_are_distinct(scenario, mode):
    g = scenario["gate"](mode)
    s = scenario["state"]
    s["accounts"].clear()
    denied("VENI_ACCOUNT_INACTIVE", lambda: scenario["check"](g, mode))
    s["accounts"].add(scenario["account"])
    s["memberships"].clear()
    denied("SCHOOL_MEMBERSHIP_REQUIRED", lambda: scenario["check"](g, mode))
    s["memberships"].add((scenario["account"], scenario["org_a"]))
    s["grants"].clear()
    denied("EXACT_SCHEDULE_GRANT_REQUIRED", lambda: scenario["check"](g, mode))


@pytest.mark.parametrize("mode", ["SHARED_AUTH", "OAUTH_HANDOFF"])
def test_no_cross_school_or_unsupported_timetable_operation(scenario, mode):
    g = scenario["gate"](mode)
    denied("SCHOOL_MEMBERSHIP_REQUIRED", lambda: scenario["check"](
        g, mode, schedule_key="school-b-options"))
    denied("UNKNOWN_SERVER_SCHEDULE", lambda: scenario["check"](
        g, mode, schedule_key="attacker-supplied-school"))
    denied("ACTION_NOT_IN_PREFLIGHT", lambda: scenario["check"](g, mode, action="publish"))


@pytest.mark.parametrize("mode", ["SHARED_AUTH", "OAUTH_HANDOFF"])
def test_expired_future_and_excessive_token_timeframes_rejected(scenario, mode):
    g = scenario["gate"](mode)
    s = scenario["state"]
    original = s["tokens"][CREDENTIAL]
    for claim_change in ({"expires_at": int(time()) - 5},
                         {"issued_at": int(time()) + 100},
                         {"expires_at": original.issued_at + 100000}):
        s["tokens"][CREDENTIAL] = replace(original, **claim_change)
        denied("STALE_OR_EXCESSIVE_SESSION", lambda: scenario["check"](g, mode))
    s["tokens"][CREDENTIAL] = original


def test_shared_auth_subject_is_canonical_veni_uuid(scenario):
    g = scenario["gate"]()
    scenario["state"]["tokens"][CREDENTIAL] = replace(
        scenario["state"]["tokens"][CREDENTIAL], subject="some-email@example.test")
    denied("INVALID_CANONICAL_ACCOUNT_ID", lambda: scenario["check"](g))


@pytest.mark.parametrize("links", [[], ["duplicate"], ["revoked"], ["pending"], ["unverified"],
                                    ["wrong-issuer"], ["wrong-subject"]])
def test_oauth_needs_exact_single_active_verified_subject_link(scenario, links):
    g = scenario["gate"]("OAUTH_HANDOFF")
    state = scenario["state"]
    first = state["links"][0]
    cases = {
        "duplicate": [first, first],
        "revoked": [replace(first, state="REVOKED")],
        "pending": [replace(first, state="PENDING")],
        "unverified": [replace(first, verified=False)],
        "wrong-issuer": [replace(first, issuer="https://other.example/auth/v1")],
        "wrong-subject": [replace(first, subject="different-opaque-identifier")],
    }
    state["links"] = cases[links[0]] if links else []
    expected = ("ACCOUNT_LINK_MISSING_OR_AMBIGUOUS" if not links or links == ["duplicate"]
                else "ACCOUNT_LINK_NOT_VERIFIED_ACTIVE")
    denied(expected, lambda: scenario["check"](g, "OAUTH_HANDOFF"))


def test_oauth_email_equivalence_and_paid_entitlement_do_not_link_accounts(scenario):
    g = scenario["gate"]("OAUTH_HANDOFF")
    s = scenario["state"]
    s["links"] = []
    # Even with an active central account and school permissions, no explicit
    # issuer+subject link means no crossover, regardless of matching email.
    denied("ACCOUNT_LINK_MISSING_OR_AMBIGUOUS", lambda: scenario["check"](g, "OAUTH_HANDOFF"))


def test_trusted_service_failures_must_deny_not_fall_back(scenario):
    g = scenario["gate"](current_session=lambda *args: 1 / 0)
    denied("SESSION_ORACLE_UNAVAILABLE", lambda: scenario["check"](g))
    g = scenario["gate"]("OAUTH_HANDOFF", verified_links=lambda *args: 1 / 0)
    denied("ACCOUNT_LINK_LOOKUP_UNAVAILABLE", lambda: scenario["check"](g, "OAUTH_HANDOFF"))
    g = scenario["gate"](current_membership=lambda *args: 1 / 0)
    denied("MEMBERSHIP_LOOKUP_UNAVAILABLE", lambda: scenario["check"](g))
    g = scenario["gate"](exact_schedule_grant=lambda *args: 1 / 0)
    denied("SCHEDULE_GRANT_LOOKUP_UNAVAILABLE", lambda: scenario["check"](g))


def test_preflight_configuration_does_not_accept_unpinned_or_browser_defined_inputs(scenario):
    with pytest.raises(ValueError): scenario["gate"](approved_transport="UNKNOWN")
    with pytest.raises(ValueError): scenario["gate"](pinned_issuer="http://untrusted.example")
    with pytest.raises(TypeError): scenario["gate"](trusted_verify=None)
    with pytest.raises(TypeError): scenario["gate"]("OAUTH_HANDOFF", verified_links=None)
    with pytest.raises(ValueError): scenario["gate"](registrations={})


def test_c10_is_disconnected_review_code_not_a_new_supabase_migration_or_http_api():
    root = Path(__file__).resolve().parents[1]
    source = (root / "veni_grid_authority/c10_account_preflight.py").read_text()
    assert "class C10AccountPreflight" in source
    assert "TRANSPORT_DECISION_PENDING" in source
    assert "supabase.co" not in source and "FastAPI(" not in source
    assert "service_role" not in source
    assert not (root / "supabase/migrations").exists()
