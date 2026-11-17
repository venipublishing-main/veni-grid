"""C9: server-process-only C4 -> PostgreSQL C8 staging and approval reference.

NO HTTP API, real Veni session oracle, production credential loader, cookie handler,
Supabase migration, publish/restore or independent school-data import.
The connection factory and schedule registrations MUST be held by a trusted server.
PostgreSQL custom settings are *not* authentication. Test deployments use a
throwaway postgres superuser, then SET LOCAL ROLE to a NOLOGIN C8 role.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Callable, Mapping, Any
from uuid import UUID, uuid4

from veni_grid_contract.handoff_common import fingerprint
from veni_grid_contract.options_handoff import AcceptedOptions
from veni_grid_contract.option_design import option_errors
from veni_grid_integration.c4_flexible_feedback import C4Input,C4Result,review_errors
from .identity_gate import IdentityGate,bind_grid_principal,IdentityRejected


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ServerScheduleRegistration:
    """Trusted server-owned mapping: external O1/C2 IDs -> a real DB scope.

    Registrations are never derived from JWT metadata or a request's org field.
    """
    key: str
    organisation_uuid: str
    schedule_uuid: str
    c4_source_organisation_id: str
    c4_source_schedule_id: str

    def __post_init__(self):
        for attr in ("organisation_uuid", "schedule_uuid"):
            value = getattr(self, attr)
            if str(UUID(value)) != value:
                raise ValueError(f"{attr} must be a canonical server-selected UUID")
        if not self.key or not self.c4_source_organisation_id or not self.c4_source_schedule_id:
            raise ValueError("All trusted registration fields are required")


class C9BridgeFailure(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class C9ServerBridge:
    """In-process reference: no public request entrypoint or role credentials.

    Only a trusted deployment creates this object with an IdentityGate whose
    JWKS and session callbacks are server-owned, and a trusted connection factory.
    Session/member checks are re-evaluated for *every* stage/approve request.
    """
    def __init__(self, *, identity_gate: IdentityGate,
                 trusted_db_connect: Callable[[], Any],
                 trusted_registrations: Mapping[str, ServerScheduleRegistration]):
        if not isinstance(identity_gate, IdentityGate) or not callable(trusted_db_connect):
            raise TypeError("Trusted identity verifier and DB factory are required")
        if not trusted_registrations or any(
            not isinstance(v, ServerScheduleRegistration) or k != v.key
            for k,v in trusted_registrations.items()
        ):
            raise ValueError("Require server-owned, explicitly typed schedule registry")
        self._identity = identity_gate
        self._open_db = trusted_db_connect
        self._reg = dict(trusted_registrations)

    def _registration(self, schedule_key: str) -> ServerScheduleRegistration:
        if not isinstance(schedule_key, str) or schedule_key not in self._reg:
            raise C9BridgeFailure("UNKNOWN_SCHEDULE")
        return self._reg[schedule_key]

    @staticmethod
    def _role(db, role: str):
        if role not in ("grid_c8_writer", "grid_c8_operator"):
            raise C9BridgeFailure("UNKNOWN_SERVER_ROLE")
        db.execute("SET LOCAL ROLE " + role)

    @staticmethod
    def _member(db, subject: str, org: str) -> bool:
        return bool(db.execute("""SELECT 1 FROM grid_private.memberships
                    WHERE organisation_id=%s AND account_id=%s AND state='ACTIVE'""",
                    (org,subject)).fetchone())

    def _identity_for(self, access_token: str, action: str, reg: ServerScheduleRegistration, db):
        identity=self._identity.verify(access_token,action=action)
        bind_grid_principal(identity,organisation_id=reg.organisation_uuid,
                            active_membership=lambda sub,org:self._member(db,sub,org))
        return identity

    @staticmethod
    def _reason(reason: str, key: str):
        if not isinstance(reason,str) or len(reason.strip())<8:
            raise C9BridgeFailure('REASON_REQUIRED')
        if not isinstance(key,str) or not (8<=len(key)<=128):
            raise C9BridgeFailure('IDEMPOTENCY_KEY_REQUIRED')
        return reason.strip()

    def stage_reviewed_c4(self, *, access_token: str, schedule_key: str,
                          request: C4Input, result: C4Result,
                          reason: str, idempotency_key: str,
                          proposal_id: str | None = None) -> dict:
        """Verify JWT + current membership + C4 independently BEFORE any write.

        The resulting approved snapshot is the full AcceptedOptions O1 object,
        not an arbitrary C4 receipt. Staging does not approve or publish.
        """
        reg=self._registration(schedule_key)
        reason=self._reason(reason,idempotency_key)
        # Authenticate and authorise BEFORE parsing potentially expensive or
        # user-supplied C4 review evidence. Repeat both checks at final commit.
        with self._open_db() as early_db:
            self._role(early_db,"grid_c8_writer")
            early_identity=self._identity_for(access_token,'propose',reg,early_db)
            if not early_db.execute("""SELECT 1 FROM grid_private.schedule_grants
                WHERE organisation_id=%s AND schedule_id=%s AND account_id=%s AND permission='propose'""",
                (reg.organisation_uuid,reg.schedule_uuid,early_identity.subject_id)).fetchone():
                raise C9BridgeFailure('PROPOSE_PERMISSION_REQUIRED')
        # Parse untrusted typed evidence and recompute its independent C4 review.
        req=C4Input.model_validate(request.model_dump(mode='json') if isinstance(request,C4Input) else request)
        res=C4Result.model_validate(result.model_dump(mode='json') if isinstance(result,C4Result) else result)
        if res.status!='PROPOSED_VALIDATED' or not res.review or not res.proposed_o1 or not res.preview_c2:
            raise C9BridgeFailure('NO_VALIDATED_PROPOSAL')
        old=req.current
        if old.target.organisation_id != reg.c4_source_organisation_id or (
            old.source_ref.organisation_id != reg.c4_source_organisation_id or
            old.source_ref.schedule_id != reg.c4_source_schedule_id):
            raise C9BridgeFailure('SOURCE_REGISTRATION_MISMATCH')
        if old.source_ref.content_sha256 != fingerprint(old.source):
            raise C9BridgeFailure('UNTRUSTED_SOURCE_FINGERPRINT')
        issues=review_errors(old,res.proposed_o1,res.preview_c2,res.review)
        if issues:
            raise C9BridgeFailure('INDEPENDENT_C4_REVIEW_FAILED')
        candidate=AcceptedOptions(demand=old.source.demand,plan=res.proposed_o1)
        if option_errors(candidate.demand,candidate.plan):
            raise C9BridgeFailure('INVALID_OPTION_WITNESS')
        # A verified review is necessary but NOT itself school authorisation.
        if proposal_id is None:
            proposal_id=str(uuid4())
        elif str(UUID(proposal_id))!=proposal_id:
            raise C9BridgeFailure('INVALID_PROPOSAL_ID')
        content=candidate.model_dump(mode='json')
        request_digest=digest({'source_hash':fingerprint(old.source),
            'candidate':content,'c4_candidate':res.review.proposed_c2_candidate_sha256,
            'source_revision':old.source_ref.revision,'reason':reason})
        with self._open_db() as db:
            self._role(db,"grid_c8_writer")
            ident=self._identity_for(access_token,'propose',reg,db)
            actor=ident.subject_id;org=reg.organisation_uuid;sid=reg.schedule_uuid
            allowed=db.execute("""SELECT 1 FROM grid_private.schedule_grants
                WHERE organisation_id=%s AND schedule_id=%s AND account_id=%s AND permission='propose'""",
                (org,sid,actor)).fetchone()
            if not allowed:raise C9BridgeFailure('PROPOSE_PERMISSION_REQUIRED')
            # The whole stage is serialised with approval's schedule row lock.
            sch=db.execute("""SELECT head_revision,head_sha256,kind,published_revision
                FROM grid_private.schedules WHERE organisation_id=%s AND id=%s FOR UPDATE""",
                (org,sid)).fetchone()
            if not sch or sch[2]!='ACADEMIC_OPTIONS':raise C9BridgeFailure('OPTIONS_SCHEDULE_REQUIRED')
            if sch[0]!=old.source_ref.revision:
                raise C9BridgeFailure('STALE_SOURCE')
            stored=db.execute("""SELECT snapshot,sha256,
                encode(public.digest(convert_to(snapshot::text,'UTF8'),'sha256'),'hex')
                FROM grid_private.accepted_versions
                WHERE organisation_id=%s AND schedule_id=%s AND revision=%s""",
                (org,sid,sch[0])).fetchone()
            # C4 uses the model's canonical fingerprint; existing C8 stored
            # revisions use PostgreSQL's JSONB::text digest. Both are checked
            # against the exact same stored option-plan *content*, so neither
            # scheme can authorise a different plan through a same-key lookup.
            if not stored or fingerprint(AcceptedOptions.model_validate(stored[0]))!=fingerprint(old.source):
                raise C9BridgeFailure('ACCEPTED_SOURCE_CONTENT_MISMATCH')
            if sch[1]!=stored[1] or sch[1] not in (fingerprint(old.source),stored[2]):
                raise C9BridgeFailure('ACCEPTED_SOURCE_HASH_SCHEME_MISMATCH')
            operation='C9_STAGE'
            replay=db.execute("""SELECT request_sha256,response FROM grid_private.operations
                 WHERE organisation_id=%s AND schedule_id=%s AND actor_id=%s
                   AND operation=%s AND idempotency_key=%s""",
                 (org,sid,actor,operation,idempotency_key)).fetchone()
            if replay:
                if replay[0]!=request_digest:raise C9BridgeFailure('IDEMPOTENCY_CONFLICT')
                return replay[1]
            # The C8 database function checks JSONB text digest at approval.
            jsondata=canonical(content)
            db.execute("""INSERT INTO grid_private.proposals(
              organisation_id,schedule_id,id,source_revision,source_sha256,payload,
              payload_sha256,state,proposed_by)
              VALUES(%s,%s,%s,%s,%s,%s::jsonb,
              encode(public.digest(convert_to((%s::jsonb)::text,'UTF8'),'sha256'),'hex'),
              'PENDING',%s)""",
              (org,sid,proposal_id,sch[0],sch[1],jsondata,jsondata,actor))
            # Source/target evidence hashes are included in an immutable audit.
            prev=db.execute("""SELECT event_sha256 FROM grid_private.audit_events
              WHERE organisation_id=%s AND schedule_id=%s ORDER BY event_id DESC LIMIT 1""",
              (org,sid)).fetchone()
            previous=prev[0] if prev else '0'*64
            detail={'proposal_id':proposal_id,'validated_c4_candidate':res.review.proposed_c2_candidate_sha256,
                    'moved_requests':len(res.review.changed_request_ids),
                    'c2_events':res.review.after_teaching_events,'source_sha256':sch[1],
                    'scope':'ACADEMIC_OPTIONS_ONLY'}
            eventhash=digest({'prior':previous,'org':org,'schedule':sid,'actor':actor,
                              'reason':reason,'detail':detail})
            db.execute("""INSERT INTO grid_private.audit_events(organisation_id,schedule_id,
               actor_id,action,reason,before_revision,after_revision,
               previous_event_sha256,event_sha256,detail)
               VALUES(%s,%s,%s,'C9_PROPOSAL_STAGED',%s,%s,%s,%s,%s,%s::jsonb)""",
               (org,sid,actor,reason,sch[0],sch[0],previous,eventhash,canonical(detail)))
            response={'proposal_id':proposal_id,'status':'PENDING',
                      'source_revision':sch[0],'source_sha256':sch[1],
                      'independently_validated':True,'published_revision':sch[3],
                      'approval':'NOT_GRANTED','publication':'NOT_GRANTED',
                      'scope':'ACADEMIC_OPTIONS_ONLY'}
            db.execute("""INSERT INTO grid_private.operations(organisation_id,schedule_id,
                    actor_id,operation,idempotency_key,request_sha256,response)
                    VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (org,sid,actor,operation,idempotency_key,request_digest,canonical(response)))
            return response

    def approve_staged(self, *, access_token: str, schedule_key: str,
                       proposal_id: str, expected_revision: int, expected_source_sha256: str,
                       reason: str, idempotency_key: str) -> dict:
        """Verified JWT + current membership, then unchanged C8 PG approval RPC.

        NO publication. C8 independently checks current approve grant, maker /
        checker, stale revision, AAL2 context, source hash and idempotency.
        """
        reg=self._registration(schedule_key)
        reason=self._reason(reason,idempotency_key)
        if str(UUID(proposal_id))!=proposal_id:
            raise C9BridgeFailure('INVALID_PROPOSAL_ID')
        with self._open_db() as db:
            # Membership validation runs under a locked server writer connection;
            # only after JWT/session validation may the operator role be assumed.
            self._role(db,"grid_c8_writer")
            identity=self._identity_for(access_token,'approve',reg,db)
            db.execute('RESET ROLE')
            self._role(db,'grid_c8_operator')
            db.execute("SELECT set_config('grid.c8_actor_id',%s,true)",(identity.subject_id,))
            db.execute("SELECT set_config('grid.c8_aal',%s,true)",(identity.assurance,))
            value=db.execute("""SELECT grid_private.c8_approve(%s,%s,%s,%s,%s,%s,%s)""",
                (reg.organisation_uuid,reg.schedule_uuid,proposal_id,expected_revision,
                 expected_source_sha256,reason,idempotency_key)).fetchone()[0]
            if value.get('timetable_published') or value.get('published_revision') is not None:
                # A published version from before approval is allowed but this
                # operation must NEVER advance the published pointer.
                pass
            return value
