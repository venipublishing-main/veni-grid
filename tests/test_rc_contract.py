"""Adversarial contract checks; no optimiser is invoked."""
import copy
from datetime import date, timedelta
from pathlib import Path
import json
import pytest
from pydantic import ValidationError
from jsonschema import Draft202012Validator, FormatChecker

from veni_grid_contract.core_v1 import (
    CoreProblem, CoreWitness, core_problem_errors, core_witness_errors,
    promote_placement, legacy_problem, legacy_witness,
)
from veni_grid_contract.recurring_claims import RecurrenceConfig, project_claims
from veni_grid_contract.flexible_options import (
    FlexibleOptionsRequest, FlexibleResult, build_flexible_handoff, flexible_handoff_errors,
)
from veni_grid_contract.handoff_common import fingerprint, HandoffError
from veni_grid_contract.primitives import ResourceClaim
from veni_grid_contract.placement_v04 import placement_witness_errors
from scripts.build_rc_fixtures import operational_pair, recurrence, flexible_request, flexible_witness


def codes(errors): return {e.code for e in errors}

def rep(p,w, mutate):
    pr,wr=p.model_dump(mode='json'),w.model_dump(mode='json');mutate(pr,wr)
    return CoreProblem.model_validate(pr),CoreWitness.model_validate(wr)


def test_operational_witness_and_lossless_base():
    p,w=operational_pair();assert not core_witness_errors(p,w)
    base=legacy_problem(p);p2,w2=promote_placement(base,legacy_witness(w))
    assert legacy_problem(p2)==base
    assert not core_witness_errors(p2,w2)


def test_qualification_is_required():
    p,w=operational_pair();p.credentials=[]
    assert 'QUALIFICATION_MISSING_OR_EXPIRED' in codes(core_witness_errors(p,w))


def test_multiple_competencies_are_all_required():
    p,w=operational_pair();p.constraints[0].all_of.append('skill:lab-safety')
    assert 'QUALIFICATION_MISSING_OR_EXPIRED' in codes(core_witness_errors(p,w))


def test_finite_qualification_needs_real_dates():
    p,w=operational_pair();raw=p.model_dump(mode='json')
    raw['credentials'][0]['valid_during']={'start':'2026-01-01T00:00:00+02:00','end':'2027-01-01T00:00:00+02:00'}
    p=CoreProblem.model_validate(raw)
    assert 'QUALIFICATION_NEEDS_DATES' in codes(core_witness_errors(p,w))


def test_qualification_covers_entire_lesson_not_only_start():
    p,w=operational_pair();raw=p.model_dump(mode='json')
    for i,d in enumerate(raw['days']):d['date']=(date(2026,11,16)+timedelta(days=i)).isoformat()
    raw['credentials'][0]['valid_during']={'start':'2026-11-16T00:00:00+02:00','end':'2026-11-16T08:20:00+02:00'}
    p=CoreProblem.model_validate(raw)
    assert 'QUALIFICATION_MISSING_OR_EXPIRED' in codes(core_witness_errors(p,w))


def test_qualified_teacher_change_breaks_continuity():
    p,w=operational_pair();w.event_assignments[1].resource_allocations[0].resource_ids=['person:teacherB']
    assert codes(core_witness_errors(p,w))=={'RESOURCE_CONTINUITY_BROKEN'}


def test_continuity_of_rooms_is_explicit_not_automatic():
    p,w=operational_pair();raw=p.model_dump(mode='json')
    raw['constraints'][1]['allocations']=[{'event_id':f'event:E{i}','requirement_id':f'req:room{i}'} for i in [1,2]]
    p=CoreProblem.model_validate(raw)
    assert 'RESOURCE_CONTINUITY_BROKEN' in codes(core_witness_errors(p,w))
    w.event_assignments[1].resource_allocations[1].resource_ids=['room:west']
    assert not core_witness_errors(p,w)


def test_team_continuity_uses_sets_not_list_order():
    p,w=operational_pair()
    for e in p.events:e.requirements[0].quantity=2
    for a in w.event_assignments:a.resource_allocations[0].resource_ids=['person:teacherA','person:teacherB']
    w.event_assignments[1].resource_allocations[0].resource_ids.reverse()
    assert not core_witness_errors(p,w)


@pytest.mark.parametrize('gap,expected',[(14,True),(15,False),(16,False)])
def test_travel_boundary(gap,expected):
    p,w=operational_pair();win=next(x for x in p.windows if x.id=='win:D1P2');win.start_minute=520+gap;win.end_minute=560+gap
    assert ('TRAVEL_GAP_TOO_SHORT' in codes(core_witness_errors(p,w))) is expected


def test_directed_travel_is_not_symmetric():
    p,w=operational_pair();w.event_assignments[0].resource_allocations[1].resource_ids=['room:east'];w.event_assignments[1].resource_allocations[1].resource_ids=['room:west']
    assert 'TRAVEL_GAP_TOO_SHORT' in codes(core_witness_errors(p,w))


def test_missing_route_is_not_assumed_zero():
    p,w=operational_pair();p.travel_arcs=[]
    assert 'TRAVEL_ROUTE_UNRESOLVED' in codes(core_witness_errors(p,w))


def test_missing_space_location_is_not_assumed_nearby():
    p,w=operational_pair();next(x for x in p.resources if x.id=='room:west').location_id=None
    assert 'TRAVEL_LOCATION_UNRESOLVED' in codes(core_witness_errors(p,w))


def test_accessible_route_profile_not_fallback_to_standard():
    p,w=operational_pair();p.resources[0].travel_profile='STEP_FREE'
    assert 'TRAVEL_ROUTE_UNRESOLVED' in codes(core_witness_errors(p,w))


def test_same_location_does_not_require_route_entry():
    p,w=operational_pair();p.travel_arcs=[];w.event_assignments[1].resource_allocations[1].resource_ids=['room:west']
    assert not core_witness_errors(p,w)


def test_learner_travel_uses_membership_expansion():
    p,w=operational_pair();p.constraints[2].resource_ids=['person:pupil1'];p.travel_arcs[0].minutes=21
    assert 'TRAVEL_GAP_TOO_SHORT' in codes(core_witness_errors(p,w))


@pytest.mark.parametrize('mutator,expected',[
    (lambda p:p['credentials'][0].update(resource_id='person:missing'),'UNKNOWN_CREDENTIAL_RESOURCE'),
    (lambda p:p['constraints'][0]['allocations'][0].update(requirement_id='req:missing'),'UNKNOWN_ALLOCATION_REF'),
    (lambda p:p['days'][1].update(ordinal=1),'DUPLICATE_DAY_ORDINAL'),
    (lambda p:p['days'][0].update(date='2026-11-16'),'MIXED_CALENDAR_KIND'),
    (lambda p:p['travel_arcs'].append(p['travel_arcs'][0].copy()),'DUPLICATE_TRAVEL_ARC'),
    (lambda p:p['constraints'][0]['all_of'].append('skill:maths'),'DUPLICATE_COMPETENCY'),
    (lambda p:p['constraints'][2]['resource_ids'].append('room:west'),'INVALID_TRAVELLER'),
    (lambda p:p['resources'][-1].update(location_id='loc:missing'),'INVALID_SPACE_LOCATION'),
    (lambda p:p['constraints'][1]['allocations'].append(p['constraints'][1]['allocations'][0]),'DUPLICATE_ALLOCATION_REF'),
])
def test_structural_operational_errors(mutator,expected):
    p,w=operational_pair();raw=p.model_dump(mode='json');mutator(raw)
    assert expected in codes(core_problem_errors(CoreProblem.model_validate(raw)))


@pytest.mark.parametrize('change',[{'kind':'SOME_FUTURE_RULE'},{'strength':'SOFT'}])
def test_unknown_rule_or_unsupported_soft_operational_rule_rejected(change):
    p,w=operational_pair();raw=p.model_dump(mode='json');raw['constraints'][0].update(change)
    with pytest.raises(ValidationError):CoreProblem.model_validate(raw)


def test_cross_day_minimum_gap_regression():
    p,w=operational_pair();w.event_assignments[0].start_window_id='win:D1P3';w.event_assignments[1].start_window_id='win:D2P1'
    raw=p.model_dump(mode='json');raw['constraints'].append(dict(id='rule:ordering',kind='EVENT_BEFORE',strength='HARD',source='USER',earlier_event_id='event:E1',later_event_id='event:E2',minimum_gap_minutes=1300))
    p=CoreProblem.model_validate(raw)
    # Demonstrates the precise inherited omission, not a hypothetical defect.
    assert not placement_witness_errors(legacy_problem(p),legacy_witness(w))
    assert 'ORDER_GAP_TOO_SHORT' in codes(core_witness_errors(p,w))


def test_daily_load_checks_learners_as_well_as_teachers():
    p,w=operational_pair();raw=p.model_dump(mode='json');raw['constraints'].append(dict(id='rule:learnerload',kind='MAX_DAILY_MINUTES',strength='HARD',source='USER',resource_ids=['person:pupil1'],limit_minutes=60));p=CoreProblem.model_validate(raw)
    assert 'DAILY_LOAD_VIOLATED' in codes(core_witness_errors(p,w))


def test_projection_includes_complete_membership_claims():
    p,w=operational_pair();c=recurrence(p,w);before=(fingerprint(p),fingerprint(w),fingerprint(c));out=project_claims(p,w,c)
    assert len(out.occurrences)==4 and len(out.claims)==20
    assert {u.day_key for u in out.occurrences}=={'2026-11-16','2026-12-01'}
    assert before==(fingerprint(p),fingerprint(w),fingerprint(c))
    assert fingerprint(out)==fingerprint(project_claims(p,w,c))
    assert len({x.id for x in out.claims})==len(out.claims)


def test_holiday_cycle_advance_is_explicit():
    p,w=operational_pair();c=recurrence(p,w);c.exceptions[0].advance_cycle=True
    out=project_claims(p,w,c)
    assert {x.day_key for x in out.occurrences}=={'2026-11-16','2026-11-30'}


def test_changed_bells_recheck_travel():
    p,w=operational_pair();c=recurrence(p,w);c.bell_sets[1].periods[1].start_minute=540
    with pytest.raises(HandoffError,match='TRAVEL_GAP_TOO_SHORT'):project_claims(p,w,c)


def test_qualification_expiry_during_term_is_not_hidden_by_cycle():
    p,w=operational_pair();raw=p.model_dump(mode='json');raw['credentials'][0]['valid_during']={'start':'2026-01-01T00:00:00+02:00','end':'2026-11-30T23:59:00+02:00'};p=CoreProblem.model_validate(raw);c=recurrence(p,w)
    with pytest.raises(HandoffError,match='QUALIFICATION_MISSING_OR_EXPIRED'):project_claims(p,w,c)


def test_qualification_valid_for_whole_projected_term():
    p,w=operational_pair();raw=p.model_dump(mode='json');raw['credentials'][0]['valid_during']={'start':'2026-01-01T00:00:00+02:00','end':'2027-01-01T00:00:00+02:00'};p=CoreProblem.model_validate(raw)
    assert len(project_claims(p,w,recurrence(p,w)).occurrences)==4


def test_targeted_cancellation_preserves_other_occurrences_and_source():
    p,w=operational_pair();c=recurrence(p,w);raw=c.model_dump(mode='json');raw['cancellations']=[dict(event_id='event:E1',on_date='2026-12-01',reason='Explicit synthetic exam override',authorised_by='synthetic:reviewer')];c=RecurrenceConfig.model_validate(raw)
    out=project_claims(p,w,c);assert len(out.occurrences)==3;assert len(w.event_assignments)==2;assert p.activities[0].demand.amount==2
    assert any(u.event_id=='event:E2' and u.day_key=='2026-12-01' for u in out.occurrences)


def test_cancellation_must_match_actual_occurrence():
    p,w=operational_pair();c=recurrence(p,w);raw=c.model_dump(mode='json');raw['cancellations']=[dict(event_id='event:E1',on_date='2026-11-18',reason='bad date',authorised_by='synthetic:reviewer')]
    with pytest.raises(HandoffError,match='CANCELLATION_NOT_AN_OCCURRENCE'):project_claims(p,w,RecurrenceConfig.model_validate(raw))


@pytest.mark.parametrize('field',['problem_sha256','witness_sha256'])
def test_stale_cycle_content_is_blocked(field):
    p,w=operational_pair();c=recurrence(p,w);setattr(c,field,'0'*64)
    with pytest.raises(HandoffError,match='STALE_PROJECTION_INPUT'):project_claims(p,w,c)


@pytest.mark.parametrize('mutation,code',[
    (lambda c:c.window_periods.pop(),'INCOMPLETE_WINDOW_MAP'),
    (lambda c:c.day_cycle.pop(),'INCOMPLETE_CYCLE_MAP'),
    (lambda c:c.exceptions.append(c.exceptions[0]),'DUPLICATE_CALENDAR_EXCEPTION'),
    (lambda c:c.bell_sets[0].periods.pop(0),'MISSING_DATED_PERIOD'),
    (lambda c:setattr(c,'horizon_start',date(2026,11,15)),'INVALID_PROJECTION_HORIZON'),
])
def test_recurring_context_errors(mutation,code):
    p,w=operational_pair();c=recurrence(p,w);mutation(c)
    with pytest.raises(HandoffError,match=code):project_claims(p,w,c)


def test_external_existing_commitment_remains_an_obstacle():
    p,w=operational_pair();c=recurrence(p,w);cl=ResourceClaim.model_validate(dict(id='claim:external',schedule_id='schedule:other',entity_id='duty:other',resource_id='person:teacherA',interval=dict(start='2026-12-01T08:15:00+02:00',end='2026-12-01T08:30:00+02:00')))
    with pytest.raises(HandoffError,match='RESOURCE_OVERLAP'):project_claims(p,w,c,[cl])


def test_double_period_projection_preserves_occupancy_and_work_minutes():
    p,w=operational_pair();raw=p.model_dump(mode='json');raw['events'][0]['duration'].update(count=2,max_gap_minutes=20);raw['activities'][0]['demand']['amount']=3;p=CoreProblem.model_validate(raw);w.event_assignments[1].start_window_id='win:D1P3';c=recurrence(p,w)
    # Changed bells have 25-minute inter-period gap; explicitly use normal bells for this positive case.
    c.exceptions=c.exceptions[:1];out=project_claims(p,w,c);u=out.occurrences[0]
    assert u.work_minutes==80 and u.interval.minutes==100
    c.exceptions=recurrence(p,w).exceptions
    with pytest.raises(HandoffError,match='DATED_ADJACENCY_BROKEN'):project_claims(p,w,c)


def test_changed_bells_recheck_aligned_different_bell_regimes():
    p,w=operational_pair();raw=p.model_dump(mode='json');raw['constraints']=[]
    raw['events'][0]['fixed_participant_ids']=['person:pupil1'];raw['events'][1]['fixed_participant_ids']=['person:pupil2']
    raw['windows'].append(dict(id='win:alternate',day_id='day:D1',bell_id='bell:alternate',sequence=1,start_minute=480,end_minute=520))
    raw['events'][1]['placement']['start_window_ids'].append('win:alternate')
    raw['constraints'].append(dict(id='rule:same',kind='EVENT_SAME_START',strength='HARD',source='USER',event_ids=['event:E1','event:E2']))
    p=CoreProblem.model_validate(raw);w.event_assignments[1].start_window_id='win:alternate';w.event_assignments[1].resource_allocations[0].resource_ids=['person:teacherB'];assert not core_witness_errors(p,w)
    c=recurrence(p,w);cr=c.model_dump(mode='json');cr['window_periods'][-1]['period_key']='period:ALT'
    cr['bell_sets'][0]['periods'].append(dict(key='period:ALT',start_minute=480,end_minute=520));cr['bell_sets'][1]['periods'].append(dict(key='period:ALT',start_minute=485,end_minute=525))
    with pytest.raises(HandoffError,match='DATED_SYNCHRONISATION_BROKEN'):project_claims(p,w,RecurrenceConfig.model_validate(cr))


def test_unequal_frequency_handoff_keeps_every_lesson_and_choice():
    r=flexible_request();before=fingerprint(r);out=build_flexible_handoff(r)
    assert not flexible_handoff_errors(out);assert len(out.problem.events)==9
    assert len(out.problem.participation_requests)==12
    assert not core_witness_errors(out.problem,flexible_witness(out))
    assert fingerprint(r)==before and fingerprint(build_flexible_handoff(r))==fingerprint(out)


def test_null_alignment_must_be_explicit_not_missing():
    raw=flexible_request().model_dump(mode='json');raw['target']['bindings'][0].pop('sync_key')
    with pytest.raises(ValidationError):FlexibleOptionsRequest.model_validate(raw)


def test_missing_occurrence_cannot_silently_reduce_curriculum():
    r=flexible_request();r.target.bindings.pop()
    with pytest.raises(HandoffError,match='OCCURRENCE_MAP_INCOMPLETE'):build_flexible_handoff(r)


def test_lonely_alignment_label_is_not_a_constraint():
    r=flexible_request();r.target.bindings[0].sync_key='sync:orphan'
    with pytest.raises(HandoffError,match='INVALID_ALIGNMENT_GROUP'):build_flexible_handoff(r)


def test_reverse_check_catches_weakened_alignment_even_after_rehash():
    out=build_flexible_handoff(flexible_request());out.problem.constraints[0].enabled=False;out.receipt.output_sha256=fingerprint(out.problem)
    assert 'ALIGNMENT_CHANGED' in codes(flexible_handoff_errors(out))


def test_reverse_check_catches_lost_request_even_after_rehash():
    out=build_flexible_handoff(flexible_request());out.problem.participation_requests.pop();out.receipt.output_sha256=fingerprint(out.problem)
    assert 'REQUEST_SET_CHANGED' in codes(flexible_handoff_errors(out))


def test_reverse_check_catches_manifest_loss():
    out=build_flexible_handoff(flexible_request());out.receipt.mappings.pop()
    assert 'LINEAGE_MANIFEST_CHANGED' in codes(flexible_handoff_errors(out))


def test_rc_schemas_describe_all_positive_new_examples():
    p,w=operational_pair();c=recurrence(p,w);r=flexible_request();h=build_flexible_handoff(r)
    for obj in [p,w,c,r,h,project_claims(p,w,c)]:
        schema=type(obj).model_json_schema();Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema,format_checker=FormatChecker()).validate(obj.model_dump(mode='json'))

@pytest.mark.parametrize('folder',['fixtures/master_school','fixtures/learner_choices','fixtures/invigilation','fixtures_v03/F1_shared_capacity'])
def test_retained_scenarios_promote_explicitly_to_c1(folder):
    from veni_grid_contract.placement_v04 import PlacementProblem,PlacementWitness
    root=Path(__file__).resolve().parents[1]/folder
    pr=json.loads((root/'problem.json').read_text());wr=json.loads((root/('solution-witness.json' if (root/'solution-witness.json').exists() else 'witness.json')).read_text())
    pr['schema_version']=wr['schema_version']='0.4.0-draft'
    p,w=promote_placement(PlacementProblem.model_validate(pr),PlacementWitness.model_validate(wr))
    assert not core_witness_errors(p,w)


def test_review_distinguishes_input_candidate_search_and_publish():
    from veni_grid_contract.conformance import review_core
    p,w=operational_pair();assert review_core(p).result=='INPUT_VALIDATED_NOT_SOLVED'
    report=review_core(p,w)
    assert report.result=='CANDIDATE_HARD_VALIDATED'
    assert report.solver_execution=='NOT_RUN' and report.publish_permission=='NOT_GRANTED'
    assert report.soft_scoring=='NOT_PERFORMED'
    w.event_assignments[1].resource_allocations[0].resource_ids=['person:teacherB']
    assert review_core(p,w).result=='CANDIDATE_INVALID'


@pytest.mark.parametrize('op',['FEASIBILITY','OPTIMISE','REPAIR','DIAGNOSE','COMPARE'])
def test_no_solver_is_advertised_by_contract_package(op):
    from veni_grid_contract.conformance import execution_gate
    assert execution_gate('C1_PLACEMENT',op)[0].code=='SOLVER_NOT_IMPLEMENTED'


def test_profiles_do_not_force_other_grid_timetables():
    from veni_grid_contract.conformance import CONFORMANCE_PROFILES
    assert all(x['standalone'] and x['mandatory_other_timetables']==[] for x in CONFORMANCE_PROFILES.values())


def test_unknown_profile_and_operation_fail_closed():
    from veni_grid_contract.conformance import execution_gate
    assert execution_gate('mystery','FEASIBILITY')[0].code=='UNSUPPORTED_PROFILE'
    assert execution_gate('C1_PLACEMENT','SILENT_PUBLISH')[0].code=='UNSUPPORTED_OPERATION'
