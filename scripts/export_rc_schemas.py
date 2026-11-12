from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from veni_grid_contract.core_v1 import CoreProblem,CoreWitness
from veni_grid_contract.recurring_claims import RecurrenceConfig,ProjectionResult
from veni_grid_contract.flexible_options import FlexibleOptionsRequest,FlexibleResult
from veni_grid_contract.conformance import CoreReview,CONFORMANCE_PROFILES
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parents[1]
for name,cls in [('core-problem-rc1',CoreProblem),('core-witness-rc1',CoreWitness),('recurring-config-rc1',RecurrenceConfig),('recurring-result-rc1',ProjectionResult),('flexible-handoff-request-rc1',FlexibleOptionsRequest),('flexible-handoff-result-rc1',FlexibleResult),('core-review-rc1',CoreReview)]:
    s=cls.model_json_schema();s['$schema']='https://json-schema.org/draft/2020-12/schema';Draft202012Validator.check_schema(s)
    (ROOT/'schemas'/f'{name}.schema.json').write_text(json.dumps(s,indent=2)+'\n')
(ROOT/'conformance-profiles.json').write_text(json.dumps(CONFORMANCE_PROFILES,indent=2)+'\n')
print('Seven RC1 schemas checked and written; profile registry written.')
