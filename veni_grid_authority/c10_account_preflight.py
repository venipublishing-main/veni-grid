"""C10 offline identity-transport preflight; never an authentication endpoint.

The Veni platform has not ratified whether Spheres share one Supabase Auth
session or exchange identity through an OAuth/PKCE handoff. This *disabled by
default* server-side reference models both without choosing one or changing
C9's signed Supabase JWT requirement. No network, user provisioning or writes.

``VerifierAssertion`` and ``ScopedPreflight`` are plain Python data, NOT
credentials. Only a trusted server may configure the verifier and callbacks;
it must independently check signatures/code exchange, issuer, audience,
session revocation and MFA before it supplies the assertion. A production C9
stage/approval must still repeat its own live membership and grant checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Callable, Literal, Mapping, Sequence
from uuid import UUID

from .c9_server_bridge import ServerScheduleRegistration

Transport = Literal["SHARED_AUTH", "OAUTH_HANDOFF"]
Action = Literal["view", "propose", "approve"]


class AccountPreflightRejected(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class VerifierAssertion:
    """A trusted-verifier output, never a browser-supplied identity object.

    For OAUTH_HANDOFF the subject identifies the upstream issuer's account;
    session_id identifies a newly validated *server-owned* local session, not
    an unverified authorisation code or the subject's email address.
    """

    transport: Transport
    issuer: str
    audience: str
    subject: str
    session_id: str
    assurance: Literal["aal1", "aal2"]
    issued_at: int
    expires_at: int


@dataclass(frozen=True)
class AccountLink:
    """Server-owned, explicitly verified upstream-subject ↔ Veni UUID link."""

    issuer: str
    subject: str
    account_uuid: str
    state: Literal["ACTIVE", "PENDING", "REVOKED"]
    verified: bool


@dataclass(frozen=True)
class ScopedPreflight:
    """A one-request policy result, NOT a bearer token or DB authority."""

    account_uuid: str
    organisation_uuid: str
    schedule_uuid: str
    action: Action
    transport: Transport
    assurance: Literal["aal1", "aal2"]


def _uuid(value: str) -> str:
    try:
        canonical = str(UUID(value))
        if canonical != value:
            raise ValueError("Noncanonical UUID")
        return canonical
    except (ValueError, TypeError, AttributeError):
        raise AccountPreflightRejected("INVALID_CANONICAL_ACCOUNT_ID") from None


class C10AccountPreflight:
    """Server-only candidate policy; approved_transport=None ALWAYS denies.

    Each configured callback is trusted server infrastructure, never a
    function or URL chosen by the browser. Local test doubles are synthetic.
    """

    def __init__(
        self, *,
        approved_transport: Transport | None = None,
        pinned_issuer: str | None = None,
        pinned_audience: str | None = None,
        trusted_verify: Callable[[str, Action], VerifierAssertion] | None = None,
        current_session: Callable[[str, str, str], bool] | None = None,
        current_account: Callable[[str], bool] | None = None,
        verified_links: Callable[[str, str], Sequence[AccountLink]] | None = None,
        current_membership: Callable[[str, str], bool] | None = None,
        exact_schedule_grant: Callable[[str, str, str, Action], bool] | None = None,
        registrations: Mapping[str, ServerScheduleRegistration] | None = None,
    ):
        if approved_transport is not None and approved_transport not in ("SHARED_AUTH", "OAUTH_HANDOFF"):
            raise ValueError("Unknown transport cannot be approved")
        if approved_transport is not None:
            if not (isinstance(pinned_issuer, str) and pinned_issuer.startswith("https://")
                    and isinstance(pinned_audience, str) and pinned_audience):
                raise ValueError("Pinned HTTPS issuer and audience required")
            required = (trusted_verify, current_session, current_account,
                        current_membership, exact_schedule_grant)
            if not all(callable(f) for f in required):
                raise TypeError("All server verification, session and permission callbacks required")
            if approved_transport == "OAUTH_HANDOFF" and not callable(verified_links):
                raise TypeError("OAuth requires exact verified account-link resolver")
            if not registrations or any(not isinstance(v, ServerScheduleRegistration) or k != v.key
                                        for k, v in registrations.items()):
                raise ValueError("Server-owned schedule registry required")
        self._transport = approved_transport
        self._issuer = pinned_issuer
        self._audience = pinned_audience
        self._verify = trusted_verify
        self._session = current_session
        self._account = current_account
        self._links = verified_links
        self._membership = current_membership
        self._grant = exact_schedule_grant
        self._registrations = dict(registrations or {})

    def for_grid(self, *, transport: Transport, credential: str, schedule_key: str,
                 action: Action) -> ScopedPreflight:
        """Fail closed: exact identity, active link, active account, school and grant.

        Even a successful result MUST NOT be passed to C9 as proof of identity;
        C9 currently accepts only a genuinely verified shared-Auth JWT.
        """
        if self._transport is None:
            raise AccountPreflightRejected("TRANSPORT_DECISION_PENDING")
        if transport != self._transport:
            raise AccountPreflightRejected("TRANSPORT_NOT_APPROVED")
        if action not in ("view", "propose", "approve"):
            raise AccountPreflightRejected("ACTION_NOT_IN_PREFLIGHT")
        if not isinstance(schedule_key, str) or schedule_key not in self._registrations:
            raise AccountPreflightRejected("UNKNOWN_SERVER_SCHEDULE")
        if not isinstance(credential, str) or not 8 <= len(credential) <= 16384:
            raise AccountPreflightRejected("INVALID_OPAQUE_CREDENTIAL")

        try:
            proof = self._verify(credential, action)
        except Exception:
            raise AccountPreflightRejected("TRUSTED_VERIFIER_UNAVAILABLE_OR_DENIED") from None
        if not isinstance(proof, VerifierAssertion):
            raise AccountPreflightRejected("TRUSTED_VERIFIER_REQUIRED")
        if (proof.transport != self._transport or proof.issuer != self._issuer
                or proof.audience != self._audience):
            raise AccountPreflightRejected("UNPINNED_IDENTITY_PROVIDER")
        if (not isinstance(proof.subject, str) or not proof.subject or len(proof.subject) > 255
                or not isinstance(proof.session_id, str)):
            raise AccountPreflightRejected("MALFORMED_VERIFIED_SESSION")
        _uuid(proof.session_id)
        now = int(time())
        if (type(proof.issued_at) is not int or type(proof.expires_at) is not int
                or proof.issued_at > now + 10 or proof.expires_at <= now
                or not 0 < proof.expires_at - proof.issued_at <= 7200):
            raise AccountPreflightRejected("STALE_OR_EXCESSIVE_SESSION")
        if proof.assurance not in ("aal1", "aal2"):
            raise AccountPreflightRejected("INVALID_ASSURANCE")
        if action == "approve" and proof.assurance != "aal2":
            raise AccountPreflightRejected("MFA_STEP_UP_REQUIRED")

        try:
            active = self._session(proof.issuer, proof.subject, proof.session_id)
        except Exception:
            raise AccountPreflightRejected("SESSION_ORACLE_UNAVAILABLE") from None
        if active is not True:
            raise AccountPreflightRejected("SESSION_REVOKED_OR_MISSING")

        if self._transport == "SHARED_AUTH":
            account_id = _uuid(proof.subject)
        else:
            # No self-asserted emails, implied account creation, or optional
            # subject matching. Every external subject requires ONE active,
            # explicitly verified, issuer-bound link to a central Veni UUID.
            try:
                links = self._links(proof.issuer, proof.subject)
                if not isinstance(links, (list, tuple)):
                    raise TypeError("Unbounded/invalid link response")
            except Exception:
                raise AccountPreflightRejected("ACCOUNT_LINK_LOOKUP_UNAVAILABLE") from None
            if len(links) != 1:
                raise AccountPreflightRejected("ACCOUNT_LINK_MISSING_OR_AMBIGUOUS")
            link = links[0]
            if (not isinstance(link, AccountLink) or link.issuer != proof.issuer
                    or link.subject != proof.subject or link.state != "ACTIVE"
                    or link.verified is not True):
                raise AccountPreflightRejected("ACCOUNT_LINK_NOT_VERIFIED_ACTIVE")
            account_id = _uuid(link.account_uuid)

        try:
            account_active = self._account(account_id)
        except Exception:
            raise AccountPreflightRejected("ACCOUNT_STATUS_UNAVAILABLE") from None
        if account_active is not True:
            raise AccountPreflightRejected("VENI_ACCOUNT_INACTIVE")

        registration = self._registrations[schedule_key]
        try:
            member = self._membership(account_id, registration.organisation_uuid)
        except Exception:
            raise AccountPreflightRejected("MEMBERSHIP_LOOKUP_UNAVAILABLE") from None
        if member is not True:
            raise AccountPreflightRejected("SCHOOL_MEMBERSHIP_REQUIRED")
        try:
            granted = self._grant(account_id, registration.organisation_uuid,
                                  registration.schedule_uuid, action)
        except Exception:
            raise AccountPreflightRejected("SCHEDULE_GRANT_LOOKUP_UNAVAILABLE") from None
        if granted is not True:
            raise AccountPreflightRejected("EXACT_SCHEDULE_GRANT_REQUIRED")

        return ScopedPreflight(account_uuid=account_id,
                               organisation_uuid=registration.organisation_uuid,
                               schedule_uuid=registration.schedule_uuid,
                               action=action, transport=self._transport,
                               assurance=proof.assurance)
