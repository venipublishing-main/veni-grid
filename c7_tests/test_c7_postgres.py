"""Executed against a real disposable PostgreSQL 17 service in GitHub CI.

These tests prove *current default-deny integrity*, NOT production user auth,
not a tenant-write API, not an already deployed Supabase RLS policy.
"""
from __future__ import annotations
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest

from .conftest import TABLES, EXPECTED_DB, expect_sqlstate


def test_actual_postgres17_and_exact_disposable_database(pg_setup):
    assert pg_setup['db']==EXPECTED_DB
    assert 170000<=pg_setup['version']<180000
    assert 'UNAPPLIED REVIEW DDL' in pg_setup['sql']


def test_actual_all_eight_tables_have_enable_and_force_rls(conn):
    rows=conn.execute('''SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity
         FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
         WHERE n.nspname='grid_private' AND c.relkind='r' ORDER BY c.relname''').fetchall()
    assert {x[0] for x in rows}==set(TABLES)
    assert all(x[1] and x[2] for x in rows)


def test_zero_exposed_rls_policies_actual_postgres(conn):
    assert conn.execute('SELECT count(*) FROM pg_policies WHERE schemaname=%s',('grid_private',)).fetchone()[0]==0
    assert not conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='grid_users'").fetchone()


@pytest.mark.parametrize('role',['anon','authenticated','service_role'])
def test_no_browser_or_service_data_api_grants(conn,role):
    assert not conn.execute("SELECT has_schema_privilege(%s,'grid_private','USAGE')",(role,)).fetchone()[0]
    for table in TABLES:
        assert not conn.execute('SELECT has_table_privilege(%s,%s,%s)',
                   (role,'grid_private.'+table,'SELECT')).fetchone()[0]
        assert not conn.execute('SELECT has_table_privilege(%s,%s,%s)',
                   (role,'grid_private.'+table,'INSERT')).fetchone()[0]
    assert not conn.execute("SELECT has_function_privilege(%s,'grid_private.reject_immutable_change()','EXECUTE')",(role,)).fetchone()[0]


def test_authenticated_role_direct_select_is_denied_even_with_existing_rows(conn,two_schools):
    conn.execute('SAVEPOINT tryclient')
    conn.execute('SET LOCAL ROLE authenticated')
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT * FROM grid_private.schedules').fetchall()
    finally:
        conn.execute('ROLLBACK TO SAVEPOINT tryclient')
        conn.execute('RELEASE SAVEPOINT tryclient')


def test_accidental_select_grant_still_yields_zero_rows_from_rls(conn,two_schools):
    # Demonstrates defense in depth. All temporary grants are rolled back.
    conn.execute('GRANT USAGE ON SCHEMA grid_private TO authenticated')
    conn.execute('GRANT SELECT ON grid_private.schedules TO authenticated')
    conn.execute('SAVEPOINT rlsrole')
    conn.execute('SET LOCAL ROLE authenticated')
    try:
        assert conn.execute('SELECT count(*) FROM grid_private.schedules').fetchone()[0]==0
    finally:
        conn.execute('ROLLBACK TO SAVEPOINT rlsrole')
        conn.execute('RELEASE SAVEPOINT rlsrole')


def test_accidental_insert_grant_is_still_denied_by_rls(conn):
    conn.execute('GRANT USAGE ON SCHEMA grid_private TO authenticated')
    conn.execute('GRANT INSERT ON grid_private.organisations TO authenticated')
    conn.execute('SAVEPOINT insertrole')
    conn.execute('SET LOCAL ROLE authenticated')
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('INSERT INTO grid_private.organisations(id,display_name) VALUES(%s,%s)',
                         (str(uuid4()),'Invented Attempt'))
    finally:
        conn.execute('ROLLBACK TO SAVEPOINT insertrole')
        conn.execute('RELEASE SAVEPOINT insertrole')


def test_membership_requires_existing_central_auth_user(conn,two_schools):
    x=two_schools
    expect_sqlstate(conn,'23503',
        "INSERT INTO grid_private.memberships(organisation_id,account_id,state,role) VALUES(%s,%s,'ACTIVE','MEMBER')",
        (x['a'],str(uuid4())))


def test_malicious_cross_tenant_schedule_grant_fk_refused(conn,two_schools):
    x=two_schools
    expect_sqlstate(conn,'23503',
      "INSERT INTO grid_private.schedule_grants(organisation_id,schedule_id,account_id,permission,granted_by) VALUES(%s,%s,%s,'approve',%s)",
      (x['a'],x['sb'],x['ua'],x['ua']))


def test_malicious_cross_tenant_membership_grant_fk_refused(conn,two_schools):
    x=two_schools
    expect_sqlstate(conn,'23503',
      "INSERT INTO grid_private.schedule_grants(organisation_id,schedule_id,account_id,permission,granted_by) VALUES(%s,%s,%s,'approve',%s)",
      (x['a'],x['sa'],x['ub'],x['ua']))


@pytest.mark.parametrize('table,statement',[
('accepted_versions', "INSERT INTO grid_private.accepted_versions(organisation_id,schedule_id,revision,snapshot,sha256,accepted_by) VALUES(%s,%s,2,'{}'::jsonb,%s,%s)"),
('proposals', "INSERT INTO grid_private.proposals(organisation_id,schedule_id,source_revision,source_sha256,payload,payload_sha256,proposed_by) VALUES(%s,%s,1,%s,'{}'::jsonb,%s,%s)"),
('operations', "INSERT INTO grid_private.operations(organisation_id,schedule_id,actor_id,operation,idempotency_key,request_sha256,response) VALUES(%s,%s,%s,'APPROVE','deduplicator','%s','{}'::jsonb)"),
('audit_events', "INSERT INTO grid_private.audit_events(organisation_id,schedule_id,actor_id,action,reason,previous_event_sha256,event_sha256) VALUES(%s,%s,%s,'STAGE','Invented school action',%s,%s)")
])
def test_other_cross_tenant_fk_scoping(conn,two_schools,table,statement):
    x=two_schools
    if table=='accepted_versions':args=(x['a'],x['sb'],'c'*64,x['ua'])
    elif table=='proposals':args=(x['a'],x['sb'],'a'*64,'b'*64,x['ua'])
    elif table=='operations':
        statement=statement.replace("'%s'","%s")
        args=(x['a'],x['sb'],x['ua'],'b'*64)
    else:args=(x['a'],x['sb'],x['ua'],'0'*64,'f'*64)
    expect_sqlstate(conn,'23503',statement,args)


def test_proposal_missing_original_version_fk_refused(conn,two_schools):
    x=two_schools
    expect_sqlstate(conn,'23503',
      "INSERT INTO grid_private.proposals(organisation_id,schedule_id,source_revision,source_sha256,payload,payload_sha256,proposed_by) VALUES(%s,%s,99,%s,'{}'::jsonb,%s,%s)",
      (x['a'],x['sa'],'a'*64,'c'*64,x['ua']))


def test_sql_accept_versions_cannot_be_updated_or_deleted(conn,two_schools):
    x=two_schools
    expect_sqlstate(conn,'23514',"UPDATE grid_private.accepted_versions SET sha256=%s WHERE organisation_id=%s AND schedule_id=%s AND revision=1",('e'*64,x['a'],x['sa']))
    expect_sqlstate(conn,'23514',"DELETE FROM grid_private.accepted_versions WHERE organisation_id=%s AND schedule_id=%s AND revision=1",(x['a'],x['sa']))


def test_sql_audit_history_cannot_be_updated_or_deleted(conn,two_schools):
    x=two_schools
    conn.execute("INSERT INTO grid_private.audit_events(organisation_id,schedule_id,actor_id,action,reason,previous_event_sha256,event_sha256) VALUES (%s,%s,%s,'STAGE','Synthetic authorised review',%s,%s)",
                 (x['a'],x['sa'],x['ua'],'0'*64,'f'*64))
    expect_sqlstate(conn,'23514',"UPDATE grid_private.audit_events SET reason='Changed after fact' WHERE organisation_id=%s AND schedule_id=%s",(x['a'],x['sa']))
    expect_sqlstate(conn,'23514',"DELETE FROM grid_private.audit_events WHERE organisation_id=%s AND schedule_id=%s",(x['a'],x['sa']))


def test_sql_proposal_content_immutable_but_state_allowed(conn,two_schools):
    x=two_schools; pid=str(uuid4())
    conn.execute('''INSERT INTO grid_private.proposals(organisation_id,schedule_id,id,source_revision,
                 source_sha256,payload,payload_sha256,proposed_by) VALUES(%s,%s,%s,1,%s,%s::jsonb,%s,%s)''',
                 (x['a'],x['sa'],pid,'a'*64,'{"draft":1}','c'*64,x['ua']))
    expect_sqlstate(conn,'23514',"UPDATE grid_private.proposals SET payload=%s::jsonb WHERE organisation_id=%s AND schedule_id=%s AND id=%s",('{"draft":2}',x['a'],x['sa'],pid))
    count=conn.execute("UPDATE grid_private.proposals SET state='APPROVED' WHERE organisation_id=%s AND schedule_id=%s AND id=%s",(x['a'],x['sa'],pid)).rowcount
    assert count==1


def test_composite_idempotency_key_is_unique_in_database(conn,two_schools):
    x=two_schools
    args=(x['a'],x['sa'],x['ua'],'APPROVE','duplicate-request','a'*64)
    sql="INSERT INTO grid_private.operations(organisation_id,schedule_id,actor_id,operation,idempotency_key,request_sha256,response) VALUES(%s,%s,%s,%s,%s,%s,'{}'::jsonb)"
    conn.execute(sql,args)
    expect_sqlstate(conn,'23505',sql,args)


def test_revision_cas_first_succeeds_stale_second_fails(conn,two_schools):
    x=two_schools
    sql='''UPDATE grid_private.schedules SET head_revision=2,head_sha256=%s
            WHERE organisation_id=%s AND id=%s AND head_revision=1 AND head_sha256=%s'''
    assert conn.execute(sql,('c'*64,x['a'],x['sa'],'a'*64)).rowcount==1
    assert conn.execute(sql,('d'*64,x['a'],x['sa'],'a'*64)).rowcount==0
    assert conn.execute('SELECT head_revision,head_sha256 FROM grid_private.schedules WHERE organisation_id=%s AND id=%s',(x['a'],x['sa'])).fetchone()==(2,'c'*64)


def test_restoration_is_new_revision_and_publishing_remains_separate(conn,two_schools):
    x=two_schools
    conn.execute("UPDATE grid_private.schedules SET head_revision=2,head_sha256=%s,published_revision=1 WHERE organisation_id=%s AND id=%s",('c'*64,x['a'],x['sa']))
    conn.execute("INSERT INTO grid_private.accepted_versions(organisation_id,schedule_id,revision,snapshot,sha256,parent_revision,accepted_by) VALUES(%s,%s,2,%s::jsonb,%s,1,%s)", (x['a'],x['sa'],'{"version":2}','c'*64,x['ua']))
    conn.execute("UPDATE grid_private.schedules SET head_revision=3,head_sha256=%s WHERE organisation_id=%s AND id=%s AND head_revision=2",('a'*64,x['a'],x['sa']))
    conn.execute("INSERT INTO grid_private.accepted_versions(organisation_id,schedule_id,revision,snapshot,sha256,parent_revision,accepted_by) VALUES(%s,%s,3,%s::jsonb,%s,2,%s)", (x['a'],x['sa'],'{"version":1}','a'*64,x['ua']))
    assert conn.execute('SELECT head_revision,published_revision FROM grid_private.schedules WHERE organisation_id=%s AND id=%s',(x['a'],x['sa'])).fetchone()==(3,1)
    assert conn.execute('SELECT count(*) FROM grid_private.accepted_versions WHERE organisation_id=%s AND schedule_id=%s',(x['a'],x['sa'])).fetchone()[0]==3


def test_simultaneous_postgres_compare_and_swap_only_one_wins(pg_setup):
    # ACTUAL PostgreSQL row lock/CAS contention using two independently connected writers.
    dsn=pg_setup['dsn']; org,sid=str(uuid4()),str(uuid4())
    with psycopg.connect(dsn,autocommit=True) as root:
        root.execute('INSERT INTO grid_private.organisations(id,display_name) VALUES(%s,%s)',(org,'Invented Concurrent School'))
        root.execute("INSERT INTO grid_private.schedules(organisation_id,id,kind,label,head_revision,head_sha256) VALUES(%s,%s,'ACADEMIC_OPTIONS','Invented Concurrent Plan',1,%s)",(org,sid,'a'*64))
    gate=threading.Barrier(2)
    def attempt(tag):
        with psycopg.connect(dsn,connect_timeout=10) as db:
            with db.transaction():
                gate.wait(timeout=10)
                changed=db.execute("UPDATE grid_private.schedules SET head_revision=2,head_sha256=%s WHERE organisation_id=%s AND id=%s AND head_revision=1 AND head_sha256=%s",(tag*64,org,sid,'a'*64)).rowcount
            return changed
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,['b','c']))
    assert sorted(results)==[0,1]
    with psycopg.connect(dsn,autocommit=True) as root:
        assert root.execute('SELECT head_revision FROM grid_private.schedules WHERE organisation_id=%s AND id=%s',(org,sid)).fetchone()[0]==2
