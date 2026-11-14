"""C5 tenant-scoped SQLite reference transactions; synthetic fixtures only."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import sqlite3
import pytest

from scripts.run_c4_probes import crossed_multi_occurrence_fixture
from veni_grid_integration.c4_flexible_feedback import propose_c4
from veni_grid_contract.handoff_common import fingerprint
from veni_grid_authority import AuthorityStore, Principal, AuthorityFailure


@pytest.fixture(scope='module')
def real_c4_case():
    """Actually run the existing C4 option+teaching solvers, not a forged receipt."""
    source=crossed_multi_occurrence_fixture()
    result=propose_c4(source)
    assert result.status=='PROPOSED_VALIDATED',result.findings
    assert result.review and result.preview_c2 and result.preview_c2.independent_hard_validation=='PASSED'
    return source,result


@pytest.fixture
def work(tmp_path,real_c4_case):
    request,result=real_c4_case
    owner=Principal('org:synthetic','user:owner')
    proposer=Principal('org:synthetic','user:proposer')
    approver=Principal('org:synthetic','user:approver')
    publisher=Principal('org:synthetic','user:publisher')
    restorer=Principal('org:synthetic','user:restorer')
    viewer=Principal('org:synthetic','user:viewer')
    store=AuthorityStore(tmp_path/'reference.sqlite',development_bootstrap=True)
    schedule=request.current.source_ref.schedule_id
    store.bootstrap(owner,schedule,request.current.source)
    for actor in (proposer,approver,publisher,restorer,viewer):
        store.add_member(owner,actor.subject_id,reason='Test tenant role provision')
    for actor,permissions in [(proposer,['propose','view']),(approver,['approve','view']),
                              (publisher,['publish','view']),(restorer,['restore','view']),
                              (viewer,['view'])]:
        for permission in permissions:
            store.grant(owner,schedule,actor.subject_id,permission,reason='Explicit test permission')
    yield {'store':store,'owner':owner,'proposer':proposer,'approver':approver,
           'publisher':publisher,'restorer':restorer,'viewer':viewer,'request':request,
           'result':result,'sid':schedule,'db':tmp_path/'reference.sqlite'}
    store.close()


def denied(code,call):
    with pytest.raises(AuthorityFailure) as exc:call()
    assert exc.value.code==code,str(exc.value)


def stage(w,who='proposer',name='proposal:one',key='stage-key-1234'):
    return w['store'].stage_c4(w[who],w['sid'],name,w['request'],w['result'],
                               reason='Propose qualified teaching improvement',idem_key=key)


def approve(w,name='proposal:one',key='approve-key-1234',expected=1):
    return w['store'].approve_c4(w['approver'],w['sid'],name,expected_revision=expected,
                                  reason='Reviewed source and all student changes',idem_key=key)


def test_staged_proposal_is_versioned_but_does_not_change_current_or_publish(work):
    w=work;old=w['store'].get_state(w['owner'],w['sid'])
    a=stage(w)
    assert a['state']=='PENDING' and a['publication']=='NOT_GRANTED'
    now=w['store'].get_state(w['owner'],w['sid'])
    assert now==old and now['published_revision'] is None
    assert w['store'].get_version(w['viewer'],w['sid'],1)['hash']==fingerprint(w['request'].current.source)


def test_actual_c4_independently_verified_approval_creates_new_immutable_version(work):
    w=work;stage(w)
    r=approve(w)
    assert r['approved_revision']==2 and r['published_revision'] is None
    assert r['academic_timetable_publication']=='NOT_GRANTED'
    state=w['store'].get_state(w['owner'],w['sid'])
    assert state['revision']==2 and state['published_revision'] is None
    one=w['store'].get_version(w['owner'],w['sid'],1)
    two=w['store'].get_version(w['owner'],w['sid'],2)
    assert one['hash']!=two['hash']
    assert len(one['accepted_options']['plan']['offerings'])==10
    assert len(two['accepted_options']['plan']['offerings'])==9
    assert len(two['accepted_options']['plan']['allocations'])==48
    assert two['parent_revision']==1 and two['source_proposal']=='proposal:one'


def test_separate_explicit_publish_only_changes_option_pointer(work):
    w=work;stage(w);approve(w)
    assert w['store'].get_state(w['owner'],w['sid'])['published_revision'] is None
    pub=w['store'].publish_current(w['publisher'],w['sid'],expected_revision=2,
                                    reason='Publish accepted option revision only',idem_key='publish-revision2')
    assert pub['published_revision']==2 and pub['publication_scope']=='OPTION_VERSION_POINTER_ONLY'
    assert pub['external_distribution']=='NOT_IMPLEMENTED'
    assert w['store'].get_state(w['viewer'],w['sid'])['published_revision']==2


def test_unrelated_school_cannot_use_other_school_authority(work,real_c4_case):
    w=work;other=Principal('org:other','user:owner')
    denied('PERMISSION_DENIED',lambda:w['store'].get_state(other,w['sid']))
    denied('PERMISSION_DENIED',lambda:w['store'].stage_c4(other,w['sid'],'x',w['request'],w['result'],
         reason='Malicious cross-tenant proposal',idem_key='cross-tenant-attempt'))
    w['store'].bootstrap(other,w['sid'],real_c4_case[0].current.source)
    other_state=w['store'].get_state(other,w['sid'])
    assert other_state['revision']==1
    stage(w);approve(w)
    assert w['store'].get_state(other,w['sid'])['revision']==1


def test_forged_principal_identity_without_membership_has_no_authority(work):
    w=work
    imposter=Principal('org:synthetic','user:imposter')
    denied('PERMISSION_DENIED',lambda:w['store'].get_state(imposter,w['sid']))
    denied('PERMISSION_DENIED',lambda:w['store'].approve_c4(imposter,w['sid'],'a',
         expected_revision=1,reason='Unauthorized approval should fail',idem_key='forged-identity11'))


def test_member_grants_are_scoped_to_exact_schedule_namespace(work):
    w=work;other='sched:other-independent-exam'
    w['store'].bootstrap(w['owner'],other,w['request'].current.source,kind='EXAMINATIONS')
    denied('PERMISSION_DENIED',lambda:w['store'].get_state(w['viewer'],other))
    assert w['store'].get_state(w['owner'],other)['kind']=='EXAMINATIONS'
    stage(w);approve(w)
    assert w['store'].get_state(w['owner'],other)['revision']==1


def test_maker_cannot_self_approve_even_with_approval_permission(work):
    w=work
    a=w['store'].stage_c4(w['owner'],w['sid'],'self',w['request'],w['result'],
        reason='Admin initiates improvement request',idem_key='owner-stage-1234')
    assert a['state']=='PENDING'
    denied('TWO_PERSON_REVIEW_REQUIRED',lambda:w['store'].approve_c4(w['owner'],w['sid'],'self',
        expected_revision=1,reason='Trying to self approve a proposal',idem_key='owner-approve-1234'))


def test_stale_parallel_preview_refused_without_partial_version(work):
    w=work
    stage(w)
    stage(w,name='proposal:two',key='stage-other-123')
    approve(w)
    denied('STALE_SOURCE',lambda:approve(w,'proposal:two','approve-other-1234',expected=2))
    assert w['store'].get_state(w['owner'],w['sid'])['revision']==2
    denied('VERSION_NOT_FOUND',lambda:w['store'].get_version(w['owner'],w['sid'],3))


def test_stale_browser_revision_is_rejected_while_newer_head_stays_intact(work):
    w=work;stage(w);approve(w)
    denied('STALE_SOURCE',lambda:w['store'].publish_current(w['publisher'],w['sid'],
       expected_revision=1,reason='Attempt publication of stale source',idem_key='publish-stale-12'))
    assert w['store'].get_state(w['owner'],w['sid'])['published_revision'] is None


def test_approval_idempotency_replay_returns_original_result_without_duplicate_audit(work):
    w=work;stage(w)
    a=approve(w);before=len(w['store'].audit_trail(w['owner'],w['sid']))
    b=approve(w)
    assert a==b
    assert len(w['store'].audit_trail(w['owner'],w['sid']))==before
    assert w['store'].get_state(w['owner'],w['sid'])['revision']==2


def test_idempotency_key_cannot_be_reused_for_different_action_payload(work):
    w=work;stage(w);approve(w)
    denied('IDEMPOTENCY_CONFLICT',lambda:w['store'].approve_c4(w['approver'],w['sid'],'proposal:one',
        expected_revision=1,reason='A different reason to hijack key',idem_key='approve-key-1234'))


def test_rollback_creates_new_version_and_never_silently_republishes(work):
    w=work;stage(w);approve(w)
    w['store'].publish_current(w['publisher'],w['sid'],expected_revision=2,
                reason='Publish second option revision',idem_key='publish-option-2')
    old=w['store'].get_version(w['owner'],w['sid'],1)
    restore=w['store'].restore(w['restorer'],w['sid'],1,expected_revision=2,
           reason='Restore original options after review',idem_key='restore-key-1234')
    assert restore['revision']==3 and restore['hash']==old['hash']
    assert restore['published_revision']==2
    state=w['store'].get_state(w['owner'],w['sid'])
    assert state['revision']==3 and state['published_revision']==2
    assert w['store'].get_version(w['owner'],w['sid'],2)['source_proposal']=='proposal:one'
    w['store'].publish_current(w['publisher'],w['sid'],expected_revision=3,
            reason='Publish manually approved restoration',idem_key='publish-restoration')
    assert w['store'].get_state(w['owner'],w['sid'])['published_revision']==3


def test_restore_replay_does_not_create_fourth_version(work):
    w=work;stage(w);approve(w)
    a=w['store'].restore(w['restorer'],w['sid'],1,expected_revision=2,
               reason='Restore original approved layout',idem_key='restore-original-1')
    b=w['store'].restore(w['restorer'],w['sid'],1,expected_revision=2,
               reason='Restore original approved layout',idem_key='restore-original-1')
    assert a==b and w['store'].get_state(w['owner'],w['sid'])['revision']==3


def test_immutable_versions_and_append_only_audit_enforced_by_database(work):
    w=work;stage(w);approve(w)
    with pytest.raises(sqlite3.IntegrityError,match='IMMUTABLE_VERSION'):
        w['store'].db.execute("UPDATE versions SET plan_hash='oops' WHERE revision=1")
    with pytest.raises(sqlite3.IntegrityError,match='APPEND_ONLY_AUDIT'):
        w['store'].db.execute("DELETE FROM audit WHERE action='PROVISION'")
    assert w['store'].verify_audit(w['owner'],w['sid'])


def test_permission_revocation_takes_effect_even_on_operation_replay(work):
    w=work;stage(w)
    w['store'].revoke(w['owner'],w['sid'],w['proposer'].subject_id,'propose',
                      reason='Revoke scheduling authority explicitly')
    denied('PERMISSION_DENIED',lambda:stage(w))
    assert w['store'].verify_audit(w['owner'],w['sid'])


def test_reviewer_can_view_but_not_approve_publish_or_restore(work):
    w=work
    assert w['store'].get_state(w['viewer'],w['sid'])['revision']==1
    denied('PERMISSION_DENIED',lambda:w['store'].approve_c4(w['viewer'],w['sid'],'none',
       expected_revision=1,reason='Unapproved review-only action',idem_key='view-approve-111'))
    denied('PERMISSION_DENIED',lambda:w['store'].publish_current(w['viewer'],w['sid'],
       expected_revision=1,reason='Unapproved review-only publish',idem_key='view-publish-111'))
    denied('PERMISSION_DENIED',lambda:w['store'].restore(w['viewer'],w['sid'],1,
       expected_revision=2,reason='Unapproved review-only restore',idem_key='view-restore-111'))


def test_reason_and_idempotency_fields_are_not_optional(work):
    w=work
    denied('REASON_REQUIRED',lambda:w['store'].stage_c4(w['proposer'],w['sid'],'p',
      w['request'],w['result'],reason='yes',idem_key='stage-key-2222'))
    denied('INVALID_IDEMPOTENCY_KEY',lambda:w['store'].stage_c4(w['proposer'],w['sid'],'p',
      w['request'],w['result'],reason='A reasonable valid reason',idem_key='short'))


def test_tampered_source_or_review_refused_before_database_stage(work):
    w=work
    bad=w['result'].model_copy(deep=True)
    bad.review.changed_request_ids=[]
    denied('INDEPENDENT_REVIEW_FAILED',lambda:w['store'].stage_c4(w['proposer'],w['sid'],'bad',
       w['request'],bad,reason='Tried altered review receipt',idem_key='tampered-review-11'))
    assert w['store'].get_state(w['owner'],w['sid'])['revision']==1


def test_bootstrap_is_disabled_without_explicit_local_provisioning_mode(tmp_path,real_c4_case):
    a=AuthorityStore(tmp_path/'closed.sqlite')
    denied('BOOTSTRAP_DISABLED',lambda:a.bootstrap(Principal('org:new','owner'),
            'schedule:new',real_c4_case[0].current.source))
    a.close()


def test_cross_process_sqlite_view_and_stale_revision_is_not_a_fake_success(work):
    w=work;stage(w)
    other=AuthorityStore(w['db'])
    assert other.get_state(w['owner'],w['sid'])['revision']==1
    approve(w)
    denied('STALE_SOURCE',lambda:other.approve_c4(w['owner'],w['sid'],'proposal:one',
            expected_revision=1,reason='Attempt stale second approval',idem_key='stale-cross-process'))
    assert other.get_state(w['owner'],w['sid'])['revision']==2
    other.close()


def test_full_hashed_audit_history_includes_separate_approval_publish_and_restore(work):
    w=work;stage(w);approve(w)
    w['store'].publish_current(w['publisher'],w['sid'],expected_revision=2,
        reason='Publish option revision two',idem_key='audit-publish-2')
    w['store'].restore(w['restorer'],w['sid'],1,expected_revision=2,
        reason='Restore an earlier option set',idem_key='audit-restore-1')
    actions=[r['action'] for r in w['store'].audit_trail(w['viewer'],w['sid'])]
    assert actions==['PROVISION','PERMISSION_GRANTED','PERMISSION_GRANTED','PERMISSION_GRANTED',
                     'PERMISSION_GRANTED','PERMISSION_GRANTED','PERMISSION_GRANTED','PERMISSION_GRANTED',
                     'PERMISSION_GRANTED','PERMISSION_GRANTED','PROPOSAL_STAGED','PROPOSAL_APPROVED',
                     'OPTION_VERSION_PUBLISHED','OPTION_VERSION_RESTORED']
    assert w['store'].verify_audit(w['viewer'],w['sid'])


def test_no_live_school_or_other_timetable_publish_side_effect(work):
    w=work;other='sched:separate-invigilation'
    w['store'].bootstrap(w['owner'],other,w['request'].current.source,kind='INVIGILATION')
    stage(w);approve(w)
    w['store'].publish_current(w['publisher'],w['sid'],expected_revision=2,
           reason='Publish option snapshot only',idem_key='no-cross-publish')
    inv=w['store'].get_state(w['owner'],other)
    assert inv['revision']==1 and inv['published_revision'] is None
