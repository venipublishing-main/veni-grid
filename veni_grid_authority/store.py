"""C5 v0.1: tenant-scoped, append-only timetable authority reference backend.

SQLite is a local transactional PROTOTYPE. ``Principal`` MUST be injected by a
trusted upstream authentication/session verifier in any real application.
No HTTP endpoint, OAuth token verification, RLS, real school data, production
Supabase integration or publication to third-party services is included here.

The approved resource is an O1 option-plan snapshot. A validated teaching
preview does NOT automatically become an accepted/published academic timetable.
Other scheduling verticals remain completely independent (GRID-D021).
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any

from veni_grid_contract.handoff_common import fingerprint
from veni_grid_contract.options_handoff import AcceptedOptions
from veni_grid_contract.option_design import option_errors
from veni_grid_integration.c4_flexible_feedback import (C4Input, C4Result, review_errors)

PERMISSIONS = frozenset({'view', 'propose', 'approve', 'publish', 'restore'})
GENESIS = '0' * 64


@dataclass(frozen=True)
class Principal:
    """Already-verified principal from a future trusted Veni Account adapter.

    It is NOT a credential and proves nothing by itself. Do not construct this
    from browser-provided user IDs, emails, JWT claims without verification,
    or content of a proposal. No exposed API exists in this reference module.
    """
    organisation_id: str
    subject_id: str


class AuthorityFailure(ValueError):
    def __init__(self, code: str, detail: str = ''):
        self.code = code
        super().__init__(f'{code}: {detail}' if detail else code)


def canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


def digest(data: Any) -> str:
    return sha256(canonical(data).encode('utf-8')).hexdigest()


def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS organisations (
 org_id TEXT PRIMARY KEY, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
 org_id TEXT NOT NULL, subject_id TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('OWNER','MEMBER')),
 state TEXT NOT NULL CHECK(state IN ('ACTIVE','REVOKED')),
 PRIMARY KEY(org_id,subject_id),
 FOREIGN KEY(org_id) REFERENCES organisations(org_id)
);
CREATE TABLE IF NOT EXISTS schedules (
 org_id TEXT NOT NULL, schedule_id TEXT NOT NULL, kind TEXT NOT NULL,
 head_revision INTEGER NOT NULL CHECK(head_revision>=1),
 head_hash TEXT NOT NULL, published_revision INTEGER,
 created_at TEXT NOT NULL,
 PRIMARY KEY(org_id,schedule_id),
 FOREIGN KEY(org_id) REFERENCES organisations(org_id)
);
CREATE TABLE IF NOT EXISTS versions (
 org_id TEXT NOT NULL, schedule_id TEXT NOT NULL,
 revision INTEGER NOT NULL CHECK(revision>=1),
 plan_json TEXT NOT NULL, plan_hash TEXT NOT NULL,
 parent_revision INTEGER, source_proposal TEXT,
 created_by TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(org_id,schedule_id,revision),
 FOREIGN KEY(org_id,schedule_id) REFERENCES schedules(org_id,schedule_id)
);
CREATE TRIGGER IF NOT EXISTS versions_no_update BEFORE UPDATE ON versions
 BEGIN SELECT RAISE(ABORT,'IMMUTABLE_VERSION'); END;
CREATE TRIGGER IF NOT EXISTS versions_no_delete BEFORE DELETE ON versions
 BEGIN SELECT RAISE(ABORT,'IMMUTABLE_VERSION'); END;
CREATE TABLE IF NOT EXISTS grants (
 org_id TEXT NOT NULL, schedule_id TEXT NOT NULL, subject_id TEXT NOT NULL,
 permission TEXT NOT NULL, granted_by TEXT NOT NULL, granted_at TEXT NOT NULL,
 PRIMARY KEY(org_id,schedule_id,subject_id,permission),
 FOREIGN KEY(org_id,schedule_id) REFERENCES schedules(org_id,schedule_id)
);
CREATE TABLE IF NOT EXISTS proposals (
 org_id TEXT NOT NULL, schedule_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
 source_revision INTEGER NOT NULL, source_hash TEXT NOT NULL,
 content_json TEXT NOT NULL, content_hash TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('PENDING','APPROVED','REJECTED')),
 created_by TEXT NOT NULL, created_at TEXT NOT NULL,
 approved_revision INTEGER,
 PRIMARY KEY(org_id,schedule_id,proposal_id),
 FOREIGN KEY(org_id,schedule_id) REFERENCES schedules(org_id,schedule_id)
);
CREATE TRIGGER IF NOT EXISTS proposals_content_immutable BEFORE UPDATE ON proposals
 WHEN OLD.content_json != NEW.content_json OR OLD.content_hash != NEW.content_hash
 OR OLD.source_revision != NEW.source_revision OR OLD.source_hash != NEW.source_hash
 OR OLD.created_by != NEW.created_by OR OLD.created_at != NEW.created_at
 BEGIN SELECT RAISE(ABORT,'IMMUTABLE_PROPOSAL'); END;
CREATE TABLE IF NOT EXISTS audit (
 event_no INTEGER PRIMARY KEY AUTOINCREMENT,
 org_id TEXT NOT NULL, schedule_id TEXT NOT NULL,
 action TEXT NOT NULL, actor_id TEXT NOT NULL, reason TEXT NOT NULL,
 previous_revision INTEGER, new_revision INTEGER,
 previous_hash TEXT, new_hash TEXT,
 previous_event_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
 created_at TEXT NOT NULL, detail_json TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
 BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_AUDIT'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
 BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_AUDIT'); END;
CREATE TABLE IF NOT EXISTS operations (
 org_id TEXT NOT NULL, schedule_id TEXT NOT NULL, subject_id TEXT NOT NULL,
 action TEXT NOT NULL, idem_key TEXT NOT NULL, request_hash TEXT NOT NULL,
 response_json TEXT NOT NULL,
 PRIMARY KEY(org_id,schedule_id,subject_id,action,idem_key)
);
CREATE INDEX IF NOT EXISTS proposal_by_source ON proposals(org_id,schedule_id,source_revision);
CREATE INDEX IF NOT EXISTS audit_by_schedule ON audit(org_id,schedule_id,event_no);
'''


class AuthorityStore:
    def __init__(self, path: str | Path, *, development_bootstrap: bool = False):
        self.path = str(path)
        self.development_bootstrap = development_bootstrap
        if self.path != ':memory:':
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=15,
                                  check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=15000')
        if self.path != ':memory:': self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript(SCHEMA)

    def close(self): self.db.close()

    @contextmanager
    def _transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        else:
            self.db.execute('COMMIT')

    @staticmethod
    def _reason(reason: str):
        if not isinstance(reason, str) or len(reason.strip()) < 8:
            raise AuthorityFailure('REASON_REQUIRED', 'Supply a meaningful reason (8+ characters)')
        return reason.strip()

    @staticmethod
    def _key(key: str):
        if not isinstance(key, str) or len(key) < 8 or len(key) > 128:
            raise AuthorityFailure('INVALID_IDEMPOTENCY_KEY', '8 to 128 characters required')

    def _schedule(self, actor: Principal, sid: str):
        row = self.db.execute('SELECT * FROM schedules WHERE org_id=? AND schedule_id=?',
                             (actor.organisation_id, sid)).fetchone()
        if row is None:raise AuthorityFailure('NOT_FOUND_OR_FORBIDDEN')
        return row

    def _allowed(self, actor: Principal, sid: str, permission: str):
        if not isinstance(actor, Principal):raise AuthorityFailure('TRUSTED_PRINCIPAL_REQUIRED')
        if permission not in PERMISSIONS:raise AuthorityFailure('UNRECOGNISED_PERMISSION')
        m=self.db.execute('SELECT role,state FROM memberships WHERE org_id=? AND subject_id=?',
                          (actor.organisation_id,actor.subject_id)).fetchone()
        if m is None or m['state']!='ACTIVE':raise AuthorityFailure('PERMISSION_DENIED')
        if m['role']=='OWNER':return
        grant=self.db.execute('SELECT 1 FROM grants WHERE org_id=? AND schedule_id=? AND subject_id=? AND permission=?',
                              (actor.organisation_id,sid,actor.subject_id,permission)).fetchone()
        if not grant:raise AuthorityFailure('PERMISSION_DENIED')

    def _owner(self, actor: Principal):
        if not isinstance(actor, Principal):raise AuthorityFailure('TRUSTED_PRINCIPAL_REQUIRED')
        r=self.db.execute('SELECT role,state FROM memberships WHERE org_id=? AND subject_id=?',
                          (actor.organisation_id,actor.subject_id)).fetchone()
        if not r or r['role']!='OWNER' or r['state']!='ACTIVE':
            raise AuthorityFailure('PERMISSION_DENIED')

    def _audit(self, actor: Principal, sid: str, action: str, reason: str,
               oldrev=None, newrev=None, oldhash=None, newhash=None, detail=None):
        prev=self.db.execute('SELECT event_hash FROM audit WHERE org_id=? AND schedule_id=? ORDER BY event_no DESC LIMIT 1',
                             (actor.organisation_id,sid)).fetchone()
        previous=prev['event_hash'] if prev else GENESIS
        at=utc()
        event={'organisation_id':actor.organisation_id,'schedule_id':sid,'action':action,
               'actor':actor.subject_id,'reason':reason,'previous_revision':oldrev,
               'new_revision':newrev,'previous_hash':oldhash,'new_hash':newhash,
               'at':at,'detail':detail or {}}
        h=sha256((previous+canonical(event)).encode('utf-8')).hexdigest()
        self.db.execute('''INSERT INTO audit(org_id,schedule_id,action,actor_id,reason,
               previous_revision,new_revision,previous_hash,new_hash,previous_event_hash,event_hash,created_at,detail_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
               (actor.organisation_id,sid,action,actor.subject_id,reason,oldrev,newrev,
                oldhash,newhash,previous,h,at,canonical(detail or {})))
        return h

    def _replay(self, actor, sid, action, key, payload):
        self._key(key)
        requesthash=digest(payload)
        row=self.db.execute('''SELECT request_hash,response_json FROM operations WHERE
                   org_id=? AND schedule_id=? AND subject_id=? AND action=? AND idem_key=?''',
                   (actor.organisation_id,sid,actor.subject_id,action,key)).fetchone()
        if row:
            if row['request_hash'] != requesthash:raise AuthorityFailure('IDEMPOTENCY_CONFLICT')
            return json.loads(row['response_json']),requesthash
        return None,requesthash

    def _record(self, actor, sid, action, key, requesthash, response):
        self.db.execute('''INSERT INTO operations VALUES(?,?,?,?,?,?,?)''',
                        (actor.organisation_id,sid,actor.subject_id,action,key,requesthash,
                         canonical(response)))

    def bootstrap(self, owner: Principal, sid: str, initial: AcceptedOptions, *, kind: str='ACADEMIC_OPTIONS'):
        """Explicit TEST/PROVISIONING fixture only; disabled by default.

        Real tenants must be provisioned by a reviewed administrative migration,
        never by an unauthenticated HTTP call or a self-chosen role.
        """
        if not self.development_bootstrap:raise AuthorityFailure('BOOTSTRAP_DISABLED')
        if not isinstance(owner,Principal):raise AuthorityFailure('TRUSTED_PRINCIPAL_REQUIRED')
        p=AcceptedOptions.model_validate(initial.model_dump(mode='json') if isinstance(initial,AcceptedOptions) else initial)
        errs=option_errors(p.demand,p.plan)
        if errs:raise AuthorityFailure('INVALID_INITIAL_OPTIONS',errs[0].code)
        content=p.model_dump(mode='json');h=fingerprint(p);at=utc()
        with self._transaction():
            self.db.execute('INSERT OR IGNORE INTO organisations VALUES(?,?)',(owner.organisation_id,at))
            membership=self.db.execute('SELECT role FROM memberships WHERE org_id=? AND subject_id=?',
                                       (owner.organisation_id,owner.subject_id)).fetchone()
            # A new organisation can be provisioned once. Existing owners can add schedules;
            # a new self-appointed user cannot become owner of an existing organisation.
            any_member=self.db.execute('SELECT 1 FROM memberships WHERE org_id=? LIMIT 1',(owner.organisation_id,)).fetchone()
            if any_member and (membership is None or membership['role']!='OWNER'):
                raise AuthorityFailure('PERMISSION_DENIED')
            if not any_member:
                self.db.execute('INSERT INTO memberships VALUES(?,?,?,?)',
                                (owner.organisation_id,owner.subject_id,'OWNER','ACTIVE'))
            self.db.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,?)',
                            (owner.organisation_id,sid,kind,1,h,None,at))
            self.db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?,?,?)',
                            (owner.organisation_id,sid,1,canonical(content),h,None,None,owner.subject_id,at))
            self._audit(owner,sid,'PROVISION','Explicit synthetic tenant setup',None,1,None,h,
                        {'kind':kind})
        return {'schedule_id':sid,'revision':1,'hash':h,'published_revision':None}

    def add_member(self, owner:Principal, subject_id:str, *, reason:str):
        reason=self._reason(reason)
        with self._transaction():
            self._owner(owner)
            if subject_id==owner.subject_id:raise AuthorityFailure('SELF_MEMBERSHIP_CHANGE_BLOCKED')
            self.db.execute('''INSERT INTO memberships(org_id,subject_id,role,state) VALUES(?,?,'MEMBER','ACTIVE')
                    ON CONFLICT(org_id,subject_id) DO UPDATE SET state='ACTIVE' ''',
                    (owner.organisation_id,subject_id))
            self._audit(owner,'__MEMBERS__','MEMBER_ADDED',reason,detail={'subject':subject_id})

    def grant(self, owner: Principal, sid: str, subject_id: str, permission: str, *, reason: str):
        reason=self._reason(reason)
        with self._transaction():
            self._owner(owner);self._schedule(owner,sid)
            if permission not in PERMISSIONS:raise AuthorityFailure('UNRECOGNISED_PERMISSION')
            member=self.db.execute('SELECT state FROM memberships WHERE org_id=? AND subject_id=?',
                                   (owner.organisation_id,subject_id)).fetchone()
            if not member or member['state']!='ACTIVE':raise AuthorityFailure('MEMBER_NOT_ACTIVE')
            self.db.execute('INSERT OR IGNORE INTO grants VALUES(?,?,?,?,?,?)',
                            (owner.organisation_id,sid,subject_id,permission,owner.subject_id,utc()))
            self._audit(owner,sid,'PERMISSION_GRANTED',reason,detail={'subject':subject_id,'permission':permission})

    def revoke(self, owner: Principal, sid: str, subject_id: str, permission: str, *, reason: str):
        reason=self._reason(reason)
        with self._transaction():
            self._owner(owner);self._schedule(owner,sid)
            self.db.execute('DELETE FROM grants WHERE org_id=? AND schedule_id=? AND subject_id=? AND permission=?',
                            (owner.organisation_id,sid,subject_id,permission))
            self._audit(owner,sid,'PERMISSION_REVOKED',reason,detail={'subject':subject_id,'permission':permission})

    def _head(self, actor, sid):
        sch=self._schedule(actor,sid)
        return sch['head_revision'],sch['head_hash']

    def get_state(self, actor: Principal, sid: str):
        self._allowed(actor,sid,'view')
        sch=self._schedule(actor,sid)
        return {'organisation_id':actor.organisation_id,'schedule_id':sid,
                'kind':sch['kind'],'revision':sch['head_revision'],
                'hash':sch['head_hash'],'published_revision':sch['published_revision']}

    def get_version(self, actor: Principal, sid: str, revision: int):
        self._allowed(actor,sid,'view')
        row=self.db.execute('''SELECT * FROM versions WHERE org_id=? AND schedule_id=? AND revision=?''',
                            (actor.organisation_id,sid,revision)).fetchone()
        if not row:raise AuthorityFailure('VERSION_NOT_FOUND')
        content=json.loads(row['plan_json'])
        if fingerprint(AcceptedOptions.model_validate(content))!=row['plan_hash']:
            raise AuthorityFailure('VERSION_CORRUPTED')
        return {'revision':row['revision'],'hash':row['plan_hash'],'accepted_options':content,
                'parent_revision':row['parent_revision'],'source_proposal':row['source_proposal']}

    def stage_c4(self, actor: Principal, sid: str, proposal_id: str, request: C4Input,
                 result: C4Result, *, reason: str, idem_key: str):
        """Store evidence only after independent O1 + C2 + review verification."""
        reason=self._reason(reason)
        # Deny first: unauthorised callers must not trigger expensive solver-review
        # parsing or learn whether a guessed schedule has a valid source.
        self._allowed(actor,sid,'propose')
        req=C4Input.model_validate(request.model_dump(mode='json') if isinstance(request,C4Input) else request)
        res=C4Result.model_validate(result.model_dump(mode='json') if isinstance(result,C4Result) else result)
        if res.status!='PROPOSED_VALIDATED' or res.review is None or res.proposed_o1 is None or res.preview_c2 is None:
            raise AuthorityFailure('UNVALIDATED_PROPOSAL')
        if req.current.target.organisation_id!=actor.organisation_id or req.current.source_ref.organisation_id!=actor.organisation_id:
            raise AuthorityFailure('CROSS_TENANT_SOURCE')
        if req.current.source_ref.schedule_id!=sid:
            raise AuthorityFailure('SCHEDULE_NAMESPACE_MISMATCH')
        errors=review_errors(req.current,res.proposed_o1,res.preview_c2,res.review)
        if errors:raise AuthorityFailure('INDEPENDENT_REVIEW_FAILED',','.join(errors))
        packet={'request':req.model_dump(mode='json'),'result':res.model_dump(mode='json')}
        source_hash=fingerprint(req.current.source)
        operation={'proposal_id':proposal_id,'packet_hash':digest(packet),'reason':reason}
        with self._transaction():
            self._allowed(actor,sid,'propose')
            cached,rhash=self._replay(actor,sid,'STAGE',idem_key,operation)
            if cached is not None:return cached
            head,hashvalue=self._head(actor,sid)
            if head!=req.current.source_ref.revision or hashvalue!=source_hash:
                raise AuthorityFailure('STALE_SOURCE')
            prior=self.db.execute('SELECT 1 FROM proposals WHERE org_id=? AND schedule_id=? AND proposal_id=?',
                                  (actor.organisation_id,sid,proposal_id)).fetchone()
            if prior:raise AuthorityFailure('PROPOSAL_ID_EXISTS')
            self.db.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                            (actor.organisation_id,sid,proposal_id,head,hashvalue,
                             canonical(packet),digest(packet),'PENDING',actor.subject_id,utc(),None))
            self._audit(actor,sid,'PROPOSAL_STAGED',reason,head,head,hashvalue,hashvalue,
                        {'proposal_id':proposal_id,'packet_hash':digest(packet)})
            response={'proposal_id':proposal_id,'state':'PENDING','source_revision':head,
                      'source_hash':hashvalue,'publication':'NOT_GRANTED'}
            self._record(actor,sid,'STAGE',idem_key,rhash,response)
            return response

    def approve_c4(self, actor: Principal, sid: str, proposal_id: str,
                   *, expected_revision: int, reason: str, idem_key: str):
        reason=self._reason(reason)
        op={'proposal_id':proposal_id,'expected_revision':expected_revision,'reason':reason}
        with self._transaction():
            self._allowed(actor,sid,'approve')
            cached,rhash=self._replay(actor,sid,'APPROVE',idem_key,op)
            if cached is not None:return cached
            head,priorhash=self._head(actor,sid)
            if head!=expected_revision:raise AuthorityFailure('STALE_SOURCE')
            row=self.db.execute('SELECT * FROM proposals WHERE org_id=? AND schedule_id=? AND proposal_id=?',
                                (actor.organisation_id,sid,proposal_id)).fetchone()
            if not row:raise AuthorityFailure('PROPOSAL_NOT_FOUND')
            if row['state']!='PENDING':raise AuthorityFailure('PROPOSAL_NOT_PENDING')
            if row['created_by']==actor.subject_id:raise AuthorityFailure('TWO_PERSON_REVIEW_REQUIRED')
            if row['source_revision']!=head or row['source_hash']!=priorhash:
                raise AuthorityFailure('STALE_SOURCE')
            packet=json.loads(row['content_json'])
            if digest(packet)!=row['content_hash']:raise AuthorityFailure('PROPOSAL_CORRUPTED')
            req=C4Input.model_validate(packet['request']);res=C4Result.model_validate(packet['result'])
            if req.current.source_ref.revision!=head or fingerprint(req.current.source)!=priorhash:
                raise AuthorityFailure('SOURCE_PROVENANCE_FAILED')
            if req.current.target.organisation_id!=actor.organisation_id or req.current.source_ref.schedule_id!=sid:
                raise AuthorityFailure('CROSS_TENANT_SOURCE')
            errs=review_errors(req.current,res.proposed_o1,res.preview_c2,res.review)
            if errs:raise AuthorityFailure('INDEPENDENT_REVIEW_FAILED',','.join(errs))
            current=self.db.execute('SELECT plan_json FROM versions WHERE org_id=? AND schedule_id=? AND revision=?',
                                    (actor.organisation_id,sid,head)).fetchone()
            if not current or fingerprint(AcceptedOptions.model_validate(json.loads(current['plan_json'])))!=priorhash:
                raise AuthorityFailure('VERSION_CORRUPTED')
            candidate=AcceptedOptions(demand=req.current.source.demand,plan=res.proposed_o1)
            if option_errors(candidate.demand,candidate.plan):
                raise AuthorityFailure('INDEPENDENT_OPTION_CHECK_FAILED')
            revised=canonical(candidate.model_dump(mode='json'))
            newhash=fingerprint(candidate);newrev=head+1;at=utc()
            changed=self.db.execute('''UPDATE schedules SET head_revision=?,head_hash=? WHERE
                    org_id=? AND schedule_id=? AND head_revision=? AND head_hash=?''',
                    (newrev,newhash,actor.organisation_id,sid,head,priorhash)).rowcount
            if changed!=1:raise AuthorityFailure('STALE_SOURCE')
            self.db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?,?,?)',
                            (actor.organisation_id,sid,newrev,revised,newhash,head,proposal_id,
                             actor.subject_id,at))
            self.db.execute("UPDATE proposals SET state='APPROVED',approved_revision=? WHERE org_id=? AND schedule_id=? AND proposal_id=?",
                            (newrev,actor.organisation_id,sid,proposal_id))
            self._audit(actor,sid,'PROPOSAL_APPROVED',reason,head,newrev,priorhash,newhash,
                        {'proposal_id':proposal_id,'candidate_hash':res.review.proposed_c2_candidate_sha256,
                         'separate_academic_timetable':'NOT_APPROVED_OR_PUBLISHED'})
            response={'schedule_id':sid,'approved_revision':newrev,'accepted_option_hash':newhash,
                      'published_revision':self._schedule(actor,sid)['published_revision'],
                      'academic_timetable_publication':'NOT_GRANTED'}
            self._record(actor,sid,'APPROVE',idem_key,rhash,response)
            return response

    def publish_current(self, actor: Principal, sid: str, *, expected_revision:int,
                        reason:str, idem_key:str):
        reason=self._reason(reason)
        op={'expected_revision':expected_revision,'reason':reason}
        with self._transaction():
            self._allowed(actor,sid,'publish')
            cached,rhash=self._replay(actor,sid,'PUBLISH',idem_key,op)
            if cached is not None:return cached
            sch=self._schedule(actor,sid)
            if sch['head_revision']!=expected_revision:raise AuthorityFailure('STALE_SOURCE')
            if sch['published_revision']==expected_revision:raise AuthorityFailure('ALREADY_PUBLISHED')
            self.db.execute('UPDATE schedules SET published_revision=? WHERE org_id=? AND schedule_id=?',
                            (expected_revision,actor.organisation_id,sid))
            self._audit(actor,sid,'OPTION_VERSION_PUBLISHED',reason,expected_revision,expected_revision,
                        sch['head_hash'],sch['head_hash'],
                        {'published_revision':expected_revision,'previous_published_revision':sch['published_revision'],
                         'external_delivery':'NOT_IMPLEMENTED'})
            response={'published_revision':expected_revision,'schedule_id':sid,
                      'publication_scope':'OPTION_VERSION_POINTER_ONLY',
                      'external_distribution':'NOT_IMPLEMENTED'}
            self._record(actor,sid,'PUBLISH',idem_key,rhash,response)
            return response

    def restore(self, actor:Principal, sid:str, target_revision:int, *,expected_revision:int,
                reason:str, idem_key:str):
        reason=self._reason(reason)
        op={'target_revision':target_revision,'expected_revision':expected_revision,'reason':reason}
        with self._transaction():
            self._allowed(actor,sid,'restore')
            cached,rhash=self._replay(actor,sid,'RESTORE',idem_key,op)
            if cached is not None:return cached
            sch=self._schedule(actor,sid)
            if sch['head_revision']!=expected_revision:raise AuthorityFailure('STALE_SOURCE')
            if target_revision>=expected_revision or target_revision<1:
                raise AuthorityFailure('INVALID_RESTORE_TARGET')
            target=self.db.execute('SELECT * FROM versions WHERE org_id=? AND schedule_id=? AND revision=?',
                                   (actor.organisation_id,sid,target_revision)).fetchone()
            if not target:raise AuthorityFailure('VERSION_NOT_FOUND')
            payload=AcceptedOptions.model_validate(json.loads(target['plan_json']))
            if fingerprint(payload)!=target['plan_hash'] or option_errors(payload.demand,payload.plan):
                raise AuthorityFailure('VERSION_CORRUPTED')
            newrev=expected_revision+1
            updated=self.db.execute('UPDATE schedules SET head_revision=?,head_hash=? WHERE org_id=? AND schedule_id=? AND head_revision=?',
                                    (newrev,target['plan_hash'],actor.organisation_id,sid,expected_revision)).rowcount
            if updated!=1:raise AuthorityFailure('STALE_SOURCE')
            self.db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?,?,?)',
                            (actor.organisation_id,sid,newrev,target['plan_json'],target['plan_hash'],expected_revision,
                             f'RESTORE:{target_revision}',actor.subject_id,utc()))
            self._audit(actor,sid,'OPTION_VERSION_RESTORED',reason,expected_revision,newrev,
                        sch['head_hash'],target['plan_hash'],{'restored_from':target_revision,
                                                             'previous_published_revision':sch['published_revision']})
            response={'revision':newrev,'restored_from':target_revision,'hash':target['plan_hash'],
                      'published_revision':sch['published_revision'],'publication':'NOT_AUTOMATIC'}
            self._record(actor,sid,'RESTORE',idem_key,rhash,response)
            return response

    def audit_trail(self, actor:Principal, sid:str):
        self._allowed(actor,sid,'view')
        rows=self.db.execute('''SELECT * FROM audit WHERE org_id=? AND schedule_id=? ORDER BY event_no''',
                             (actor.organisation_id,sid)).fetchall()
        return [{k:r[k] for k in r.keys()} for r in rows]

    def verify_audit(self, actor:Principal, sid:str) -> bool:
        """Detect accidental/malicious row changes; not DB-admin-grade immutability."""
        previous=GENESIS
        for row in self.audit_trail(actor,sid):
            if row['previous_event_hash']!=previous:return False
            event={'organisation_id':row['org_id'],'schedule_id':row['schedule_id'],
                   'action':row['action'],'actor':row['actor_id'],'reason':row['reason'],
                   'previous_revision':row['previous_revision'],'new_revision':row['new_revision'],
                   'previous_hash':row['previous_hash'],'new_hash':row['new_hash'],
                   'at':row['created_at'],'detail':json.loads(row['detail_json'])}
            expected=sha256((previous+canonical(event)).encode('utf-8')).hexdigest()
            if expected!=row['event_hash']:return False
            previous=expected
        return True
