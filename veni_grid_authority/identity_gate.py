"""C6 REVIEW: verify a *Veni Account* Supabase Auth JWT before Grid authority.

No browser/client API. No token scraping. A caller must supply a trusted, pinned
JWKS snapshot and a separate trusted session-status oracle. A Veni login alone
never creates school membership or a schedule grant. No live Supabase connection.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Any, Literal
from uuid import UUID
import jwt


class IdentityRejected(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class IdentityConfig:
    issuer: str
    audience: str = "authenticated"
    algorithms: tuple[str, ...] = ("RS256", "ES256")
    max_lifetime_seconds: int = 7200
    leeway_seconds: int = 10

    def __post_init__(self):
        if not self.issuer.startswith("https://") or not self.issuer.endswith("/auth/v1"):
            raise ValueError("Issuer must be an explicitly pinned Supabase Auth HTTPS origin")
        if not self.audience or set(self.algorithms) - {"RS256", "ES256"} or not self.algorithms:
            raise ValueError("Reject unpinned or symmetric JWT signature algorithms")
        if self.max_lifetime_seconds < 60 or self.max_lifetime_seconds > 86400:
            raise ValueError("Invalid maximum token lifetime")
        if self.leeway_seconds < 0 or self.leeway_seconds > 60:
            raise ValueError("Excessive token leeway")


@dataclass(frozen=True)
class VerifiedVeniIdentity:
    subject_id: str
    session_id: str
    assurance: Literal["aal1", "aal2"]
    issued_at: int
    expires_at: int
    # No organisation, role, email, or entitlements: these belong to server authorities.


class IdentityGate:
    """No network. Keys and sessions MUST come from trusted server interfaces.

    The key provider must retrieve the pinned Supabase project JWKS over HTTPS
    with a rotation-aware cache; NEVER from token headers (jku/x5u) or JSON.
    The session callback must check current revocation/session existence at the
    identity authority; JWT signature verification alone cannot revoke a token.
    """

    def __init__(self, *, config: IdentityConfig,
                 trusted_jwks: Callable[[], Mapping[str, Any]],
                 active_session: Callable[[str, str], bool]):
        if not callable(trusted_jwks) or not callable(active_session):
            raise TypeError("Trusted JWKS and revocation callbacks are required")
        self.config = config
        self._jwks = trusted_jwks
        self._active_session = active_session

    def verify(self, access_token: str, *, action: str = "view") -> VerifiedVeniIdentity:
        if action not in {"view", "propose", "approve", "publish", "restore", "grant"}:
            raise IdentityRejected("UNKNOWN_ACTION")
        if not isinstance(access_token, str) or len(access_token) < 80 or len(access_token) > 16384:
            raise IdentityRejected("INVALID_TOKEN_FORMAT")
        try:
            header = jwt.get_unverified_header(access_token)
        except (jwt.PyJWTError, ValueError):
            raise IdentityRejected("INVALID_TOKEN_HEADER") from None
        alg, kid = header.get("alg"), header.get("kid")
        if alg not in self.config.algorithms or not isinstance(kid, str) or not kid or len(kid) > 200:
            raise IdentityRejected("UNTRUSTED_KEY_OR_ALGORITHM")
        # Do not chase a token-supplied URL, nor trust an embedded JWK.
        if any(x in header for x in ("jku", "jwk", "x5u", "crit")):
            raise IdentityRejected("UNTRUSTED_TOKEN_HEADER")
        try:
            published = self._jwks()
            keys = published.get("keys")
            if not isinstance(keys, list):
                raise IdentityRejected("JWKS_UNAVAILABLE")
            matches = [k for k in keys if isinstance(k, dict) and k.get("kid") == kid]
            if len(matches) != 1:
                raise IdentityRejected("UNKNOWN_OR_DUPLICATE_SIGNING_KEY")
            key = matches[0]
            expected_type = "RSA" if alg == "RS256" else "EC"
            if key.get("kty") != expected_type or key.get("alg", alg) != alg or key.get("use", "sig") != "sig":
                raise IdentityRejected("KEY_TYPE_MISMATCH")
            if "key_ops" in key and "verify" not in key["key_ops"]:
                raise IdentityRejected("KEY_NOT_FOR_VERIFICATION")
            public = jwt.PyJWK.from_dict(key, algorithm=alg).key
            claims = jwt.decode(
                access_token, public, algorithms=[alg],
                issuer=self.config.issuer, audience=self.config.audience,
                leeway=self.config.leeway_seconds,
                options={"require": ["iss", "aud", "sub", "exp", "iat", "session_id", "role", "aal"],
                         "verify_exp": True, "verify_iat": True, "verify_nbf": True},
            )
        except IdentityRejected:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise IdentityRejected("SIGNATURE_OR_CLAIMS_INVALID") from None
        try:
            subject = str(UUID(str(claims["sub"])))
            session = str(UUID(str(claims["session_id"])))
            exp = claims["exp"]
            iat = claims["iat"]
            if type(exp) is not int or type(iat) is not int or exp <= iat or exp-iat > self.config.max_lifetime_seconds:
                raise ValueError("Invalid token lifetime")
            if claims["role"] != "authenticated" or claims.get("is_anonymous") is True:
                raise ValueError("Anonymous/service token")
            aal = claims["aal"]
            if aal not in ("aal1", "aal2"):
                raise ValueError("Unrecognised assurance")
        except (ValueError, TypeError, KeyError):
            raise IdentityRejected("ACCOUNT_CLAIMS_INVALID") from None
        if action in ("approve", "publish", "restore", "grant") and aal != "aal2":
            raise IdentityRejected("MFA_STEP_UP_REQUIRED")
        try:
            is_active = self._active_session(subject, session)
        except Exception:
            raise IdentityRejected("SESSION_STATUS_UNAVAILABLE") from None
        if is_active is not True:
            raise IdentityRejected("SESSION_NOT_ACTIVE")
        return VerifiedVeniIdentity(subject_id=subject,session_id=session,assurance=aal,
                                    issued_at=iat,expires_at=exp)


def bind_grid_principal(identity: VerifiedVeniIdentity, *, organisation_id: str,
                        active_membership: Callable[[str, str], bool]):
    """Choose tenant on server, then independently check organisation membership.

    Deliberately never derive tenant from JWT metadata or email. The actual
    C5 store still independently enforces exact schedule-scoped operation grants.
    """
    if not isinstance(identity, VerifiedVeniIdentity):
        raise IdentityRejected("VERIFIED_IDENTITY_REQUIRED")
    if not isinstance(organisation_id, str) or not organisation_id or len(organisation_id) > 150:
        raise IdentityRejected("INVALID_TENANT_SCOPE")
    try:
        allowed=active_membership(identity.subject_id, organisation_id)
    except Exception:
        raise IdentityRejected("MEMBERSHIP_STATUS_UNAVAILABLE") from None
    if allowed is not True:
        raise IdentityRejected("GRID_MEMBERSHIP_REQUIRED")
    # Imports only the C5 in-process authority identity *after* both trust gates.
    from .store import Principal
    return Principal(organisation_id=organisation_id, subject_id=identity.subject_id)
