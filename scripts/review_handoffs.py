"""Read-only reproducible contract review. No solver, store write or publication."""
from __future__ import annotations
import json,sys
from pathlib import Path
from datetime import date,timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from veni_grid_contract.options_handoff import (OptionsHandoff,LessonHandoffResult,
    build_lesson_handoff,lesson_handoff_errors)
from veni_grid_contract.placement_v04 import PlacementWitness,placement_witness_errors
from veni_grid_contract.exam_handoff import ExamHandoffResult,exam_handoff_errors
from veni_grid_contract.coverage import CoverageWitness,coverage_errors
from veni_grid_contract.handoff_common import SnapshotRef,fingerprint
from veni_grid_contract.handoff_changes import StaffingReviewRequest,review_staffing_change
from veni_grid_contract.placement_claims import derive_dated_placement_claims


def load(folder,name):return json.loads((ROOT/'fixtures_v04'/folder/name).read_text())
def show(data):print(json.dumps(data,sort_keys=True))

lesson=LessonHandoffResult.model_validate(load('H1_options_to_lessons','handoff.json'))
lw=PlacementWitness.model_validate(load('H1_options_to_lessons','placement-witness.json'))
errors=[*lesson_handoff_errors(lesson),*placement_witness_errors(lesson.problem,lw)]
show({'case':'H1_options_to_lessons','passed':not errors,'sections':len(lesson.problem.offerings),
      'learner_requests':len(lesson.problem.participation_requests),'events':len(lesson.problem.events),
      'solver_executed':False,'errors':[str(e) for e in errors]})
assert not errors
for folder in ['H2_grid_exams_to_coverage','H3_manual_exams_to_coverage']:
    result=ExamHandoffResult.model_validate(load(folder,'handoff.json'))
    witness=CoverageWitness.model_validate(load(folder,'coverage-witness.json'))
    errors=[*exam_handoff_errors(result),*coverage_errors(result.problem,witness)]
    show({'case':folder,'passed':not errors,'sessions':len(result.problem.sessions),
          'coverage_bands':len(result.problem.demands),'staff_duties':len(witness.duties),
          'source_venue_reservations':len(result.source_reservations),'solver_executed':False,
          'errors':[str(e) for e in errors]})
    assert not errors
request=StaffingReviewRequest.model_validate(load('H4_staffing_only_change','review-request.json'))
current=[SnapshotRef.model_validate(x) for x in load('H4_staffing_only_change','authoritative-current-refs.json')]
report=review_staffing_change(request,current)
show({'case':'H4_staffing_only_change','passed':report.status=='VALIDATED_PROPOSAL_NOT_APPLIED',
      'status':report.status,'changed_duties':len(report.actual_changes),
      'complete_staff_claims':len(report.complete_target_claims),'applied':False,'solver_executed':False,
      'duty_minutes_by_person':report.duty_minutes_by_person})
assert report.status=='VALIDATED_PROPOSAL_NOT_APPLIED'
# Standalone dated instantiation, not recurrence expansion or a search result.
r=OptionsHandoff.model_validate(load('H1_options_to_lessons','request.json'))
for i,d in enumerate(r.target.days):d.date=date(2027,1,11)+timedelta(days=i)
dated=build_lesson_handoff(r);claims=derive_dated_placement_claims(dated.problem,lw)
show({'case':'H5_fully_dated_lesson_claims','passed':len(claims)==40,'all_claims':len(claims),
      'learner_claims':sum(c.resource_id.startswith('learner:') for c in claims),
      'teacher_claims':sum(c.resource_id.startswith('teacher:') for c in claims),
      'room_claims':sum(c.resource_id.startswith('room:') for c in claims),
      'solver_executed':False,'claim_manifest_sha256':fingerprint(claims)})
assert len(claims)==40
