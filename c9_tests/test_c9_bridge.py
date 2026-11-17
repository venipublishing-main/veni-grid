"""C9 integration with real synthetic C4 and disposable PostgreSQL17 C8 SQL.

Test JWKS/session/membership are deliberate test doubles, NOT live Supabase Auth.
"""
from __future__ import annotations
from uuid import uuid4
import pytest
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from veni_grid_authority.identity_gate import IdentityRejected
from veni_grid_authority.c9_server_bridge import C9BridgeFailure
from .conftest import stage,approve


def test_verified_token_stages_actual_c4_without_approval_or_publication(c9_school):
    import psycopg
    c=c9_school;r=stage(c)
    assert r['status']=='PENDING' and r['independently_validated'] and r['publication']=='NOT_GRANTED'
    with psycopg.connect(c['dsn']) as db:
        row=db.execute('''SELECT state,proposed_by,payload,payload_sha256 FROM grid_private.proposals
              WHERE id=%s AND organisation_id=%s''',(r['proposal_id'],c['org'])).fetchone()
        assert row[0]=='PENDING' and str(row[1])==c['people']['planner']
        assert len(row[2]['plan']['offerings'])==9 and len(row[2]['plan']['allocations'])==48
        head=db.execute('SELECT head_revision,published_revision FROM grid_private.schedules WHERE id=%s',(c['sid'],)).fetchone()
        assert head==(1,None)
        assert db.execute("SELECT count(*) FROM grid_private.audit_events WHERE schedule_id=%s AND action='C9_PROPOSAL_STAGED'",(c['sid'],)).fetchone()[0]==1


def test_signed_aal2_second_checker_approves_actual_independently_validated_options(c9_school):
    import psycopg
    c=c9_school;c['proposal']=stage(c)['proposal_id'];r=approve(c)
    assert r['status']=='APPROVED' and r['revision']==2
    assert not r['timetable_published'] and r['published_revision'] is None
    with psycopg.connect(c['dsn']) as db:
        row=db.execute('''SELECT snapshot FROM grid_private.accepted_versions
            WHERE organisation_id=%s AND schedule_id=%s AND revision=2''',(c['org'],c['sid'])).fetchone()
        assert row and len(row[0]['plan']['offerings'])==9 and len(row[0]['plan']['allocations'])==48
        assert db.execute('SELECT count(*) FROM grid_private.audit_events WHERE schedule_id=%s',(c['sid'],)).fetchone()[0]==2
        assert db.execute('SELECT published_revision FROM grid_private.schedules WHERE id=%s',(c['sid'],)).fetchone()[0] is None


def test_signed_identity_but_only_view_grant_cannot_stage(c9_school):
    with pytest.raises(C9BridgeFailure,match='PROPOSE_PERMISSION_REQUIRED'):
        stage(c9_school,who='viewer')


def test_wrong_school_can_never_be_selected_by_token_user_metadata(c9_school):
    c=c9_school
    with pytest.raises(IdentityRejected,match='GRID_MEMBERSHIP_REQUIRED'):
        c['bridge'].stage_reviewed_c4(access_token=c['token']('planner'),schedule_key='wrong-school-options',
            request=c['request'],result=c['result'],reason='Attempt to cross a school boundary',idempotency_key='cross-school-001')


def test_forged_jwt_rejected_before_candidate_review(c9_school):
    c=c9_school
    other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    with pytest.raises(IdentityRejected,match='SIGNATURE_OR_CLAIMS_INVALID'):
        stage(c,token=c['token']('planner',signer=other))


def test_wrong_issuer_rejected_before_database_write(c9_school):
    c=c9_school
    with pytest.raises(IdentityRejected,match='SIGNATURE_OR_CLAIMS_INVALID'):
        stage(c,token=c['token']('planner',claims={'iss':'https://malicious.test/auth/v1'}))


def test_revoked_signed_session_denied(c9_school):
    c=c9_school;c['active'].discard(c['sessions']['planner'])
    with pytest.raises(IdentityRejected,match='SESSION_NOT_ACTIVE'):
        stage(c)


def test_revoked_checker_session_after_staging_blocks_approval(c9_school):
    c=c9_school;c['proposal']=stage(c)['proposal_id'];c['active'].discard(c['sessions']['checker'])
    with pytest.raises(IdentityRejected,match='SESSION_NOT_ACTIVE'):
        approve(c)


def test_aal1_signin_cannot_authorise_approve(c9_school):
    c=c9_school;c['proposal']=stage(c)['proposal_id']
    with pytest.raises(IdentityRejected,match='MFA_STEP_UP_REQUIRED'):
        approve(c,token=c['token']('checker',aal='aal1'))


def test_maker_cannot_approve_own_staged_proposal_even_with_grant(c9_school):
    import psycopg
    c=c9_school;c['proposal']=stage(c)['proposal_id']
    with psycopg.connect(c['dsn']) as db:
        db.execute('''INSERT INTO grid_private.schedule_grants
        (organisation_id,schedule_id,account_id,permission,granted_by)
        VALUES(%s,%s,%s,'approve',%s)''',
        (c['org'],c['sid'],c['people']['planner'],c['people']['owner']))
    with pytest.raises(psycopg.Error,match='C8_MAKER_CHECKER_REQUIRED'):
        approve(c,who='planner')


def test_staging_is_idempotent_and_does_not_double_audit(c9_school):
    import psycopg
    c=c9_school;r=stage(c);again=stage(c)
    assert r==again
    with psycopg.connect(c['dsn']) as db:
        assert db.execute("SELECT count(*) FROM grid_private.proposals WHERE organisation_id=%s AND schedule_id=%s",(c['org'],c['sid'])).fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM grid_private.audit_events WHERE organisation_id=%s AND schedule_id=%s",(c['org'],c['sid'])).fetchone()[0]==1


def test_idempotency_reuse_with_changed_review_reason_is_rejected(c9_school):
    c=c9_school;stage(c)
    with pytest.raises(C9BridgeFailure,match='IDEMPOTENCY_CONFLICT'):
        stage(c,reason='Same idempotency token with altered proposal narrative')


def test_independent_c4_review_tampering_prevents_staging(c9_school):
    c=c9_school;bad=c['result'].model_copy(deep=True);bad.review.changed_request_ids=[]
    with pytest.raises(C9BridgeFailure,match='INDEPENDENT_C4_REVIEW_FAILED'):
        stage(c,result=bad)


def test_untrusted_teaching_resource_policy_cannot_replace_registered_school_policy(c9_school):
    c=c9_school;bad=c['request'].model_copy(deep=True)
    # The stored O1 options are unchanged, but this is a different teaching
    # policy from the one that the server registered for this school.
    bad.current.target.timezone='UTC'
    with pytest.raises(C9BridgeFailure,match='TARGET_POLICY_MISMATCH'):
        stage(c,request=bad)


def test_other_valid_placement_problem_cannot_be_substituted_as_c4_evidence(c9_school):
    c=c9_school;bad=c['result'].model_copy(deep=True)
    # A different timezone can leave an otherwise hard-valid C1 placement
    # witness intact. Its validity must not be treated as proof for this C4
    # proposal's exact derived school placement problem.
    bad.preview_c2.placement_problem.timezone='UTC'
    with pytest.raises(C9BridgeFailure,match='C2_PROBLEM_LINEAGE_MISMATCH'):
        stage(c,result=bad)


def test_stale_source_revision_prevents_unreviewed_overwrite(c9_school):
    import psycopg
    c=c9_school
    with psycopg.connect(c['dsn']) as db:
        db.execute('UPDATE grid_private.schedules SET head_revision=2 WHERE organisation_id=%s AND id=%s',(c['org'],c['sid']))
    with pytest.raises(C9BridgeFailure,match='STALE_SOURCE'):
        stage(c)


def test_stale_registration_cannot_be_supplied_as_request_scope(c9_school):
    c=c9_school
    with pytest.raises(C9BridgeFailure,match='UNKNOWN_SCHEDULE'):
        c['bridge'].stage_reviewed_c4(access_token=c['token']('planner'),schedule_key='unknown-tenant',
            request=c['request'],result=c['result'],reason='Attempt an unknown school route',idempotency_key='unknown-tenant-001')


def test_revoke_schedule_permission_prevents_mfa_approval(c9_school):
    import psycopg
    c=c9_school;c['proposal']=stage(c)['proposal_id']
    with psycopg.connect(c['dsn']) as db:
        db.execute("DELETE FROM grid_private.schedule_grants WHERE organisation_id=%s AND schedule_id=%s AND account_id=%s AND permission='approve'",(c['org'],c['sid'],c['people']['checker']))
    with pytest.raises(psycopg.Error,match='C8_PERMISSION_DENIED'):
        approve(c)
