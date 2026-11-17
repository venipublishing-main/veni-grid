"""C8 runs only on an independently named disposable PostgreSQL 17 database.

Both C7 and C8 live in the *same disposable container*, but in DIFFERENT
independently named test databases. Never supply a hosted Supabase DSN.
"""
from __future__ import annotations
import json,os
from pathlib import Path
from uuid import uuid4
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='session')
def pg8_setup():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    baseline=os.environ.get('GRID_C7_PG_DSN','')
    if os.environ.get('GRID_C8_DISPOSABLE_ONLY')!='YES' or not baseline or os.environ.get('GRID_C7_DISPOSABLE_ONLY')!='YES':
        raise RuntimeError('C8 refuses execution without exact double-disposable gate')
    parsed=conninfo_to_dict(baseline)
    if parsed.get('dbname')!='grid_c7_isolated' or parsed.get('host') not in ('localhost','127.0.0.1'):
        raise RuntimeError('C8 refuses any DSN other than local dedicated PG17 test service')
    with psycopg.connect(baseline,autocommit=True,connect_timeout=8) as server:
        name,role,ver=server.execute("SELECT current_database(),current_user,current_setting('server_version_num')::int").fetchone()
        if name!='grid_c7_isolated' or role!='postgres' or not 170000<=ver<180000:
            raise RuntimeError('C8 refuses wrong server, database owner or PG major')
        present=server.execute('SELECT 1 FROM pg_database WHERE datname=%s',('grid_c8_isolated',)).fetchone()
        if not present:server.execute('CREATE DATABASE grid_c8_isolated')
    dsn=make_conninfo(baseline,dbname='grid_c8_isolated')
    with psycopg.connect(dsn,autocommit=True) as db:
        target,role,ver=db.execute("SELECT current_database(),current_user,current_setting('server_version_num')::int").fetchone()
        assert target=='grid_c8_isolated' and role=='postgres' and 170000<=ver<180000
        for name in ('anon','authenticated','service_role'):
            exists=db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(name,)).fetchone()
            if not exists:db.execute('CREATE ROLE '+name+' NOLOGIN NOSUPERUSER NOBYPASSRLS')
        db.execute('CREATE SCHEMA auth')
        db.execute('CREATE TABLE auth.users (id uuid PRIMARY KEY)')
        db.execute((ROOT/'db/review/c6_grid_private_schema.sql').read_text(),prepare=False)
        db.execute((ROOT/'db/c8/c8_isolated_policy_approval.sql').read_text(),prepare=False)
    return {'dsn':dsn,'dbname':target,'version':ver}


@pytest.fixture
def school(pg8_setup):
    import psycopg
    # Seed only completely invented UUIDs and source/plan fingerprints.
    people={key:str(uuid4()) for key in ('owner_a','planner_a','checker_a','viewer_a','outsider_a','owner_b','viewer_b')}
    orgs={key:str(uuid4()) for key in ('a','b')}
    schedules={key:str(uuid4()) for key in ('a','b','exam')}
    proposal=str(uuid4()); second_proposal=str(uuid4()); src='a'*64
    payload=json.dumps({'demonstration':'SYNTHETIC_ONLY','source_revision':1,'validated_source':'C4_REFERENCE_TEST_STUB'})
    with psycopg.connect(pg8_setup['dsn']) as c:
        c.cursor().executemany('INSERT INTO auth.users(id) VALUES(%s)',[(x,) for x in people.values()])
        c.cursor().executemany('INSERT INTO grid_private.organisations(id,display_name) VALUES(%s,%s)',
                      [(orgs['a'],'Fictitious School Alpha'),(orgs['b'],'Fictitious School Beta')])
        c.cursor().executemany("INSERT INTO grid_private.memberships(organisation_id,account_id,role,state) VALUES(%s,%s,%s,'ACTIVE')",
            [(orgs['a'],people[k],('OWNER' if k=='owner_a' else 'MEMBER'))
             for k in ('owner_a','planner_a','checker_a','viewer_a','outsider_a')]+
            [(orgs['b'],people[k],('OWNER' if k=='owner_b' else 'MEMBER'))
             for k in ('owner_b','viewer_b')])
        c.cursor().executemany('''INSERT INTO grid_private.schedules(organisation_id,id,kind,label,head_revision,head_sha256)
        VALUES(%s,%s,%s,%s,1,%s)''',[
          (orgs['a'],schedules['a'],'ACADEMIC_OPTIONS','Options A',src),
          (orgs['b'],schedules['b'],'ACADEMIC_OPTIONS','Options B','b'*64),
          (orgs['a'],schedules['exam'],'EXAMINATIONS','Exams A','c'*64)])
        c.cursor().executemany('''INSERT INTO grid_private.accepted_versions(organisation_id,schedule_id,revision,snapshot,sha256,accepted_by)
          VALUES(%s,%s,1,%s::jsonb,%s,%s)''',[
           (orgs['a'],schedules['a'],'{"version":1}','a'*64,people['owner_a']),
           (orgs['b'],schedules['b'],'{"version":1}','b'*64,people['owner_b']),
           (orgs['a'],schedules['exam'],'{"version":1}','c'*64,people['owner_a'])])
        c.cursor().executemany('''INSERT INTO grid_private.schedule_grants(organisation_id,schedule_id,account_id,permission,granted_by)
        VALUES(%s,%s,%s,%s,%s)''',[
           (orgs['a'],schedules['a'],people['viewer_a'],'view',people['owner_a']),
           (orgs['a'],schedules['a'],people['checker_a'],'approve',people['owner_a']),
           (orgs['b'],schedules['b'],people['viewer_b'],'view',people['owner_b'])])
        c.cursor().executemany('''INSERT INTO grid_private.proposals(organisation_id,schedule_id,id,source_revision,
          source_sha256,payload,payload_sha256,state,proposed_by)
          VALUES(%s,%s,%s,1,%s,%s::jsonb,
              encode(public.digest(convert_to(%s::jsonb::text,'UTF8'),'sha256'),'hex'),'PENDING',%s)''',[
           (orgs['a'],schedules['a'],proposal,src,payload,payload,people['planner_a']),
           (orgs['a'],schedules['a'],second_proposal,src,payload,payload,people['planner_a'])])
    return {'people':people,'orgs':orgs,'schedules':schedules,'proposal':proposal,
            'other_proposal':second_proposal,'source_sha':src,'dsn':pg8_setup['dsn']}


def run_role(school,role,actor,query,args=None,*,aal='aal1',fetch='all'):
    """One short-lived trusted-server connection and transaction in PG test."""
    import psycopg
    if role not in ('grid_c8_reader','grid_c8_operator','anon','authenticated','service_role'):
        raise ValueError('Unknown test-only role')
    with psycopg.connect(school['dsn'],connect_timeout=8) as db:
        db.execute('SET LOCAL ROLE '+role)
        if actor:
            db.execute("SELECT set_config('grid.c8_actor_id',%s,true)",(actor,))
        if aal:
            db.execute("SELECT set_config('grid.c8_aal',%s,true)",(aal,))
        cursor=db.execute(query,args)
        if fetch=='one':return cursor.fetchone()
        if fetch=='none':return cursor.rowcount
        return cursor.fetchall()

APPROVE_SQL='''SELECT grid_private.c8_approve(%s,%s,%s,%s,%s,%s,%s)'''


def approve(school,actor='checker_a',proposal='proposal',*,rev=1,sha=None,
            reason='Independent checker approved review',idem='c8-approve-sample-001',aal='aal2'):
    return run_role(school,'grid_c8_operator',school['people'][actor],APPROVE_SQL,
       (school['orgs']['a'],school['schedules']['a'],school[proposal],rev,
        sha or school['source_sha'],reason,idem),aal=aal,fetch='one')[0]
