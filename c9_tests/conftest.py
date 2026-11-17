"""C9 synthetic integration fixtures. All identities/keys/teachers invented."""
from __future__ import annotations
from datetime import datetime,timezone
from uuid import uuid4
from pathlib import Path
import os
import json
import pytest
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

# C9 attaches to the already-created C8 PG test database, rather than
# importing C8's session fixture (which would re-create its auth schema).
# It can independently prepare the exact same disposable database when C9
# tests run alone; no C8 source modification is required.
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='session')
def c9_pg_setup():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict,make_conninfo
    if os.environ.get('GRID_C7_DISPOSABLE_ONLY')!='YES' or os.environ.get('GRID_C8_DISPOSABLE_ONLY')!='YES' or os.environ.get('GRID_C9_DISPOSABLE_ONLY')!='YES':
        raise RuntimeError('C9 refuses any PostgreSQL target without all disposable gates')
    base=os.environ.get('GRID_C7_PG_DSN','')
    p=conninfo_to_dict(base)
    if p.get('dbname')!='grid_c7_isolated' or p.get('host') not in ('localhost','127.0.0.1'):
        raise RuntimeError('C9 refuses nonlocal or unexpected PostgreSQL target')
    with psycopg.connect(base,autocommit=True,connect_timeout=10) as bootstrap:
        name,user,version=bootstrap.execute("SELECT current_database(),current_user,current_setting('server_version_num')::int").fetchone()
        if name!='grid_c7_isolated' or user!='postgres' or not 170000<=version<180000:
            raise RuntimeError('C9 refuses unsafe PostgreSQL version or role')
        exists=bootstrap.execute("SELECT 1 FROM pg_database WHERE datname='grid_c8_isolated'").fetchone()
        if not exists:bootstrap.execute('CREATE DATABASE grid_c8_isolated')
    dsn=make_conninfo(base,dbname='grid_c8_isolated')
    with psycopg.connect(dsn,autocommit=True,connect_timeout=10) as db:
        have=db.execute("SELECT to_regclass('grid_private.schedules')").fetchone()[0]
        if not have:
            for name in ('anon','authenticated','service_role'):
                if not db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(name,)).fetchone():
                    db.execute(f'CREATE ROLE {name} NOLOGIN NOSUPERUSER NOBYPASSRLS')
            db.execute('CREATE SCHEMA auth')
            db.execute('CREATE TABLE auth.users (id uuid PRIMARY KEY)')
            db.execute((ROOT/'db/review/c6_grid_private_schema.sql').read_text(),prepare=False)
            db.execute((ROOT/'db/c8/c8_isolated_policy_approval.sql').read_text(),prepare=False)
    return {'dsn':dsn,'database':'grid_c8_isolated'}
from scripts.run_c4_probes import crossed_multi_occurrence_fixture
from veni_grid_integration.c4_flexible_feedback import propose_c4
from veni_grid_contract.handoff_common import fingerprint
from veni_grid_authority.identity_gate import IdentityGate,IdentityConfig
from veni_grid_authority.c9_server_bridge import C9ServerBridge,ServerScheduleRegistration,canonical

ISS='https://synthetic-veni-c9.supabase.co/auth/v1'

@pytest.fixture(scope='session')
def real_c4():
    request=crossed_multi_occurrence_fixture()
    result=propose_c4(request)
    assert result.status=='PROPOSED_VALIDATED' and result.review.preserved_compulsory_requests==48
    assert result.review.after_teaching_events==18
    return request,result

@pytest.fixture
def c9_school(c9_pg_setup,real_c4):
    import psycopg
    request,result=real_c4
    org=str(uuid4());sid=str(uuid4());other_org=str(uuid4());other_sid=str(uuid4())
    people={k:str(uuid4()) for k in ('planner','checker','viewer','outsider','other','owner')}
    sessions={k:str(uuid4()) for k in people};active=set(sessions.values())
    with psycopg.connect(c9_pg_setup['dsn']) as db:
        db.cursor().executemany('INSERT INTO auth.users(id) VALUES(%s)',[(u,) for u in people.values()])
        db.execute('INSERT INTO grid_private.organisations(id,display_name) VALUES(%s,%s)',(org,'Imaginary School Alpha'))
        db.execute('INSERT INTO grid_private.organisations(id,display_name) VALUES(%s,%s)',(other_org,'Imaginary School Beta'))
        for person in ('planner','checker','viewer','owner'):
            db.execute("INSERT INTO grid_private.memberships(organisation_id,account_id,state,role) VALUES(%s,%s,'ACTIVE',%s)",
                       (org,people[person],'OWNER' if person=='owner' else 'MEMBER'))
        db.execute("INSERT INTO grid_private.memberships(organisation_id,account_id,state,role) VALUES(%s,%s,'ACTIVE','MEMBER')",(other_org,people['other']))
        src=fingerprint(request.current.source)
        db.execute('''INSERT INTO grid_private.schedules
            (organisation_id,id,kind,label,head_revision,head_sha256)
            VALUES(%s,%s,'ACADEMIC_OPTIONS','Imaginary Core Options',1,%s)''',(org,sid,src))
        db.execute('''INSERT INTO grid_private.schedules
            (organisation_id,id,kind,label,head_revision,head_sha256)
            VALUES(%s,%s,'ACADEMIC_OPTIONS','Imaginary Other School',1,%s)''',(other_org,other_sid,'b'*64))
        db.execute('''INSERT INTO grid_private.accepted_versions
          (organisation_id,schedule_id,revision,snapshot,sha256,accepted_by)
          VALUES(%s,%s,1,%s::jsonb,%s,%s)''',
          (org,sid,canonical(request.current.source.model_dump(mode='json')),src,people['owner']))
        for user,perm in [('planner','propose'),('checker','approve'),('viewer','view')]:
            db.execute('''INSERT INTO grid_private.schedule_grants
              (organisation_id,schedule_id,account_id,permission,granted_by)
              VALUES(%s,%s,%s,%s,%s)''',(org,sid,people[user],perm,people['owner']))
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    jwk=json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update({'kid':'synthetic-c9-key','alg':'RS256','use':'sig'})
    gate=IdentityGate(config=IdentityConfig(issuer=ISS),trusted_jwks=lambda:{'keys':[jwk]},
                      active_session=lambda sub,session:session in active and sub in people.values()
                             and session in {sessions[k] for k,v in people.items() if v==sub})
    def token(who,aal='aal2',claims=None,signer=None):
        now=int(datetime.now(timezone.utc).timestamp())
        payload={'iss':ISS,'aud':'authenticated','sub':people[who],
          'session_id':sessions[who],'iat':now,'nbf':now-1,'exp':now+1200,
          'role':'authenticated','aal':aal,'is_anonymous':False,
          'user_metadata':{'organisation_id':other_org,'is_admin':True}}
        payload.update(claims or {})
        return jwt.encode(payload,signer or private,algorithm='RS256',headers={'kid':'synthetic-c9-key'})
    reg=ServerScheduleRegistration(key='trusted-school-options',organisation_uuid=org,
        schedule_uuid=sid,c4_source_organisation_id=request.current.source_ref.organisation_id,
        c4_source_schedule_id=request.current.source_ref.schedule_id)
    reg_other=ServerScheduleRegistration(key='wrong-school-options',organisation_uuid=other_org,
        schedule_uuid=other_sid,c4_source_organisation_id=request.current.source_ref.organisation_id,
        c4_source_schedule_id=request.current.source_ref.schedule_id)
    bridge=C9ServerBridge(identity_gate=gate,
        trusted_db_connect=lambda:psycopg.connect(c9_pg_setup['dsn'],connect_timeout=8),
        trusted_registrations={'trusted-school-options':reg,'wrong-school-options':reg_other})
    return dict(bridge=bridge,token=token,people=people,sessions=sessions,active=active,
                request=request,result=result,org=org,sid=sid,other_org=other_org,
                dsn=c9_pg_setup['dsn'],src=fingerprint(request.current.source),private=private)


def stage(c,who='planner',*,token=None,idem='c9-stage-reference-001',result=None,request=None,reason='Mathematically checked option revision proposal'):
    return c['bridge'].stage_reviewed_c4(access_token=token or c['token'](who),
       schedule_key='trusted-school-options',request=request or c['request'],
       result=result or c['result'],reason=reason,idempotency_key=idem)


def approve(c,who='checker',*,token=None,proposal=None,idem='c9-approve-reference-001',reason='Independent review of learner and teacher allocations'):
    return c['bridge'].approve_staged(access_token=token or c['token'](who),
       schedule_key='trusted-school-options',proposal_id=proposal or c['proposal'],
       expected_revision=1,expected_source_sha256=c['src'],
       reason=reason,idempotency_key=idem)
