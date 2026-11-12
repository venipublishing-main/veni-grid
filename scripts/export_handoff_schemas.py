from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from veni_grid_contract.options_handoff import OptionsHandoff,LessonHandoffResult
from veni_grid_contract.placement_v04 import PlacementProblem,PlacementWitness
from veni_grid_contract.exam_handoff import ExamHandoff,ExamHandoffResult
from veni_grid_contract.handoff_changes import StaffingReviewRequest,StaffingReviewResult,CoverageState
from veni_grid_contract.handoff_common import SnapshotRef,HandoffReceipt
MODELS={'options-handoff':OptionsHandoff,'lesson-handoff-result':LessonHandoffResult,
        'placement-problem-v04':PlacementProblem,'placement-witness-v04':PlacementWitness,
        'exam-handoff':ExamHandoff,'exam-handoff-result':ExamHandoffResult,
        'staffing-review-request':StaffingReviewRequest,'staffing-review-result':StaffingReviewResult,
        'coverage-state':CoverageState,'snapshot-ref':SnapshotRef,'handoff-receipt':HandoffReceipt}
for name,cls in MODELS.items():
    schema=cls.model_json_schema();schema['$schema']='https://json-schema.org/draft/2020-12/schema'
    (ROOT/'schemas'/f'{name}.schema.json').write_text(json.dumps(schema,indent=2)+'\n')
print(f'Exported {len(MODELS)} v0.4 handoff schemas; retained dialects remain version-labelled 0.3.')
