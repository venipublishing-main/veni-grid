"""Real PostgreSQL 17 C8 evidence. This does NOT authenticate a live user.

The trusted actor/AAL GUCs are set by a disposable backend test connection,
not by a verified network session. Browser roles never inherit these roles.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import psycopg
import pytest

from .conftest import approve,run_role,APPROVE_SQL


def denied(school, actor='checker_a', proposal='proposal', *, expected='C8_PERMISSION_DENIED',
           rev=1,sha=None,reason='Independent checker approved review',
           idem='c8-denial-test-0001',aal='aal2'):
    with pytest.raises(psycopg.Error) as exc:
        approve(school,actor,proposal,rev=rev,sha=sha,reason=reason,idem=idem,aal=aal)
    assert expected in str(exc.value),str(exc.value)[:350]


def test_c8_runs_in_a_real_separate_postgres17_database(pg8_setup):
    assert pg8_setup['dbname']=='grid_c8_isolated'
    assert 170000<=pg8_setup['version']<180000


def test_c8_roles_are_nonlogin_and_do_not_bypass_rls(pg8_setup):
    with psycopg.connect(pg8_setup['dsn']) as db:
        rows=db.execute("SELECT rolname,rolcanlogin,rolsuper,rolbypassrls FROM pg_roles WHERE rolname LIKE 'grid_c8_%' ORDER BY 1").fetchall()
    assert {x[0] for x in rows}=={'grid_c8_reader','grid_c8_operator','grid_c8_writer'}
    assert all(not any(x[1:]) for x in rows)


def test_c8_maintains_force_rls_all_eight_tables(pg8_setup):
    with psycopg.connect(pg8_setup['dsn']) as db:
        flags=db.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relnamespace='grid_private'::regnamespace AND relkind='r'").fetchall()
    assert len(flags)==8 and all(a and b for _,a,b in flags)


@pytest.mark.parametrize('role',['anon','authenticated','service_role'])
def test_browser_roles_have_neither_table_access_nor_approval_function(pg8_setup,role):
    signature='grid_private.c8_approve(uuid,uuid,uuid,integer,text,text,text)'
    with psycopg.connect(pg8_setup['dsn']) as db:
        assert not db.execute("SELECT has_schema_privilege(%s,'grid_private','USAGE')",(role,)).fetchone()[0]
        assert not db.execute('SELECT has_function_privilege(%s,%s,\'EXECUTE\')',(role,signature)).fetchone()[0]
        assert not db.execute("SELECT pg_has_role(%s,'grid_c8_operator','MEMBER')",(role,)).fetchone()[0]


def test_reader_without_verified_identity_sees_no_rows(school):
    assert run_role(school,'grid_c8_reader',None,'SELECT count(*) FROM grid_private.schedules',aal=None,fetch='one')==(0,)


def test_reader_with_grant_sees_only_own_school_schedule(school):
    rows=run_role(school,'grid_c8_reader',school['people']['viewer_a'],
                  'SELECT organisation_id::text,id::text FROM grid_private.schedules ORDER BY id')
    assert rows==[(school['orgs']['a'],school['schedules']['a'])]


def test_reader_other_school_has_only_its_own_schedule(school):
    rows=run_role(school,'grid_c8_reader',school['people']['viewer_b'],
                  'SELECT organisation_id::text,id::text FROM grid_private.schedules')
    assert rows==[(school['orgs']['b'],school['schedules']['b'])]


def test_school_membership_without_schedule_grant_is_not_enough(school):
    assert run_role(school,'grid_c8_reader',school['people']['outsider_a'],
                    'SELECT id FROM grid_private.schedules')==[]


def test_owner_can_review_own_schedules_but_not_other_school(school):
    rows=run_role(school,'grid_c8_reader',school['people']['owner_a'],
                  'SELECT id::text FROM grid_private.schedules')
    assert {x[0] for x in rows}=={school['schedules']['a'],school['schedules']['exam']}


def test_revoke_membership_immediately_hides_previously_visible_schedule(school):
    with psycopg.connect(school['dsn']) as admin:
        admin.execute("UPDATE grid_private.memberships SET state='REVOKED' WHERE organisation_id=%s AND account_id=%s",
                      (school['orgs']['a'],school['people']['viewer_a']))
    assert run_role(school,'grid_c8_reader',school['people']['viewer_a'],
                    'SELECT id FROM grid_private.schedules')==[]


def test_missing_view_grant_hides_versions_and_proposals(school):
    for table in ('accepted_versions','proposals'):
        rows=run_role(school,'grid_c8_reader',school['people']['outsider_a'],
                      f'SELECT count(*) FROM grid_private.{table}',fetch='one')
        assert rows==(0,)


def test_reader_sees_only_versions_of_authorised_schedule(school):
    rows=run_role(school,'grid_c8_reader',school['people']['viewer_a'],
                  'SELECT schedule_id::text, revision FROM grid_private.accepted_versions')
    assert rows==[(school['schedules']['a'],1)]


def test_reader_cannot_update_schedules_even_if_school_grant_exists(school):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        run_role(school,'grid_c8_reader',school['people']['owner_a'],
                 'UPDATE grid_private.schedules SET label=%s WHERE id=%s',
                 ('Tampered',school['schedules']['a']),fetch='none')


def test_operator_must_use_private_approval_function_not_raw_tables(school):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        run_role(school,'grid_c8_operator',school['people']['checker_a'],
                 'SELECT * FROM grid_private.schedules')


def test_client_forging_actor_setting_still_cannot_read_private_rows(school):
    # Session-user postgres cannot model an external user SET ROLE check.
    # Privilege catalogue + SET ROLE authenticated with forged custom settings
    # prove authenticated has no direct private-table access.
    with psycopg.connect(school['dsn']) as conn:
        assert conn.execute("SELECT pg_has_role('authenticated','grid_c8_reader','MEMBER')").fetchone()==(False,)
        assert conn.execute("SELECT pg_has_role('authenticated','grid_c8_operator','MEMBER')").fetchone()==(False,)
        conn.execute('SET LOCAL ROLE authenticated')
        conn.execute("SELECT set_config('grid.c8_actor_id',%s,true)",(school['people']['owner_a'],))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT * FROM grid_private.schedules')


def test_operator_missing_actor_claim_is_denied(school):
    with pytest.raises(psycopg.Error) as exc:
        run_role(school,'grid_c8_operator',None,APPROVE_SQL,
                 (school['orgs']['a'],school['schedules']['a'],school['proposal'],1,
                  school['source_sha'],'Independent checker approval','c8-no-actor-claim'),aal='aal2')
    assert 'C8_IDENTITY_REQUIRED' in str(exc.value)


def test_high_risk_approval_requires_aal2(school):
    denied(school,expected='C8_MFA_STEP_UP_REQUIRED',aal='aal1')


def test_membership_without_approval_grant_is_denied(school):
    denied(school,actor='viewer_a',expected='C8_PERMISSION_DENIED')


def test_wrong_school_membership_cannot_approve(school):
    denied(school,actor='viewer_b',expected='C8_PERMISSION_DENIED')


def test_two_person_reviewer_cannot_approve_own_plan(school):
    with psycopg.connect(school['dsn']) as admin:
        admin.execute("INSERT INTO grid_private.schedule_grants(organisation_id,schedule_id,account_id,permission,granted_by) VALUES(%s,%s,%s,'approve',%s)",
           (school['orgs']['a'],school['schedules']['a'],school['people']['planner_a'],school['people']['owner_a']))
    denied(school,actor='planner_a',expected='C8_MAKER_CHECKER_REQUIRED')


def test_approved_version_is_immutable_and_not_published(school):
    value=approve(school)
    assert value['status']=='APPROVED' and value['revision']==2
    assert value['published_revision'] is None and not value['timetable_published']
    with psycopg.connect(school['dsn']) as admin:
        state=admin.execute('SELECT head_revision,published_revision FROM grid_private.schedules WHERE id=%s',(school['schedules']['a'],)).fetchone()
        versions=admin.execute('SELECT revision FROM grid_private.accepted_versions WHERE schedule_id=%s ORDER BY revision',(school['schedules']['a'],)).fetchall()
        audit=admin.execute('SELECT action,actor_id::text FROM grid_private.audit_events WHERE schedule_id=%s',(school['schedules']['a'],)).fetchall()
    assert state==(2,None) and versions==[(1,),(2,)]
    assert audit==[('PROPOSAL_APPROVED',school['people']['checker_a'])]


def test_approved_version_cannot_be_updated_or_deleted(school):
    approve(school)
    with psycopg.connect(school['dsn']) as admin:
        with pytest.raises(psycopg.errors.CheckViolation):
            with admin.transaction():
                admin.execute('UPDATE grid_private.accepted_versions SET snapshot=\'{}\'::jsonb WHERE schedule_id=%s AND revision=2',(school['schedules']['a'],))


def test_stale_source_revision_or_hash_refused(school):
    denied(school,rev=2,expected='C8_STALE_SOURCE')
    denied(school,sha='0'*64,expected='C8_STALE_SOURCE',idem='c8-stale-hash-token')


def test_replayed_identical_approval_returns_same_receipt_without_duplicate_write(school):
    first=approve(school)
    replay=approve(school)
    assert first==replay
    with psycopg.connect(school['dsn']) as db:
        assert db.execute('SELECT count(*) FROM grid_private.audit_events WHERE schedule_id=%s',(school['schedules']['a'],)).fetchone()[0]==1
        assert db.execute('SELECT head_revision FROM grid_private.schedules WHERE id=%s',(school['schedules']['a'],)).fetchone()[0]==2


def test_idempotency_conflict_if_reason_changes(school):
    approve(school)
    denied(school,expected='C8_IDEMPOTENCY_CONFLICT',reason='Attempt altered request with same key',idem='c8-approve-sample-001')


def test_revocation_blocks_even_exact_idempotency_replay(school):
    approve(school)
    with psycopg.connect(school['dsn']) as db:
        db.execute('DELETE FROM grid_private.schedule_grants WHERE organisation_id=%s AND schedule_id=%s AND account_id=%s AND permission=%s',
                   (school['orgs']['a'],school['schedules']['a'],school['people']['checker_a'],'approve'))
    denied(school,expected='C8_PERMISSION_DENIED',idem='c8-approve-sample-001')


def test_invalid_proposal_integrity_hash_fails_closed(school):
    # The existing C6 trigger already prevents altering stored proposal bytes.
    # Seed a deliberately bad *new* fixture to exercise C8 hash checks too.
    with psycopg.connect(school['dsn']) as admin:
        with pytest.raises(psycopg.errors.CheckViolation):
            with admin.transaction():
                admin.execute('UPDATE grid_private.proposals SET payload_sha256=%s WHERE id=%s',
                              ('0'*64,school['proposal']))
        bad_id=str(uuid4())
        admin.execute('''INSERT INTO grid_private.proposals(
          organisation_id,schedule_id,id,source_revision,source_sha256,
          payload,payload_sha256,state,proposed_by)
          VALUES(%s,%s,%s,1,%s,%s::jsonb,%s,'PENDING',%s)''',
          (school['orgs']['a'],school['schedules']['a'],bad_id,
           school['source_sha'],'{"bad_fixture":true}','0'*64,school['people']['planner_a']))
    bad_fixture={**school,'bad_proposal':bad_id}
    denied(bad_fixture,proposal='bad_proposal',expected='C8_PROPOSAL_HASH_MISMATCH')


def test_valid_reviewer_cannot_approve_nonacademic_schedule(school):
    with psycopg.connect(school['dsn']) as admin:
        admin.execute("INSERT INTO grid_private.schedule_grants(organisation_id,schedule_id,account_id,permission,granted_by) VALUES(%s,%s,%s,'approve',%s)",
            (school['orgs']['a'],school['schedules']['exam'],school['people']['checker_a'],school['people']['owner_a']))
    other=str(uuid4());payload='{"synthetic":true}'
    with psycopg.connect(school['dsn']) as admin:
        admin.execute("INSERT INTO grid_private.proposals(organisation_id,schedule_id,id,source_revision,source_sha256,payload,payload_sha256,state,proposed_by) VALUES(%s,%s,%s,1,%s,%s::jsonb,encode(public.digest(convert_to(%s::jsonb::text,'UTF8'),'sha256'),'hex'),'PENDING',%s)",
          (school['orgs']['a'],school['schedules']['exam'],other,'c'*64,payload,payload,school['people']['planner_a']))
    with pytest.raises(psycopg.Error) as exc:
        run_role(school,'grid_c8_operator',school['people']['checker_a'],APPROVE_SQL,
                 (school['orgs']['a'],school['schedules']['exam'],other,1,'c'*64,
                  'Review exam independent version','c8-exam-denial-001'),aal='aal2')
    assert 'C8_OPTIONS_ONLY' in str(exc.value)


def test_reason_and_key_required(school):
    denied(school,expected='C8_REASON_OR_IDEMPOTENCY_REQUIRED',reason='short')
    denied(school,expected='C8_REASON_OR_IDEMPOTENCY_REQUIRED',idem='x')


def test_concurrent_approval_only_one_commits(school):
    # Two different authorised reviewers each use an independent PG connection.
    org,sid,src=school['orgs']['a'],school['schedules']['a'],school['source_sha']
    with psycopg.connect(school['dsn']) as db:
        db.execute('''INSERT INTO grid_private.schedule_grants(organisation_id,schedule_id,account_id,permission,granted_by)
         VALUES(%s,%s,%s,'approve',%s)''',
          (org,sid,school['people']['viewer_a'],school['people']['owner_a']))
    from threading import Barrier
    gate=Barrier(2)
    def worker(who,proposal,idem):
        with psycopg.connect(school['dsn']) as db:
            db.execute('SET LOCAL ROLE grid_c8_operator')
            db.execute("SELECT set_config('grid.c8_actor_id',%s,true)",(school['people'][who],))
            db.execute("SELECT set_config('grid.c8_aal','aal2',true)")
            gate.wait(timeout=10)
            try:
                res=db.execute(APPROVE_SQL,(org,sid,proposal,1,src,'Independent concurrent decision',idem)).fetchone()[0]
                return ('OK',res['revision'])
            except psycopg.Error as exc:
                return ('DENIED',str(exc))
    with ThreadPoolExecutor(max_workers=2) as pool:
        out=list(pool.map(lambda args:worker(*args),[
          ('checker_a',school['proposal'],'c8-race-a-0001'),
          ('viewer_a',school['other_proposal'],'c8-race-b-0001')]))
    assert [x[0] for x in out].count('OK')==1,out
    assert any(x[0]=='DENIED' and 'C8_STALE_SOURCE' in x[1] for x in out),out
    with psycopg.connect(school['dsn']) as admin:
        assert admin.execute('SELECT head_revision FROM grid_private.schedules WHERE id=%s',(sid,)).fetchone()[0]==2
        assert admin.execute('SELECT count(*) FROM grid_private.accepted_versions WHERE schedule_id=%s',(sid,)).fetchone()[0]==2
