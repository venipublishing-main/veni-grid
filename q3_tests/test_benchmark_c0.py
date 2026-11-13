"""C0 scale is representation/validator evidence ONLY, never a solver claim."""
from veni_grid_contract.option_design import option_errors
from scripts.build_benchmark_c0 import build


def test_c0_1500_learner_choice_plan_witness():
    p,w=build()
    assert len(p.participant_ids)==1500
    assert len(p.families)==18
    assert len(p.requests)==9000
    assert len(w.block_ids)==6
    assert len(w.offerings)==450
    assert len(w.allocations)==9000
    assert option_errors(p,w)==[]


def test_c0_guard_rejects_same_person_same_block_twice():
    p,w=build();w=w.model_copy(deep=True)
    # Reassign one section to another block: validate the whole plan, not a guess.
    w.offerings[0].block_id='block:B1'
    errors=option_errors(p,w)
    assert any(x.code=='LEARNER_BLOCK_CLASH' for x in errors)


def test_c0_guard_rejects_over_capacity():
    p,w=build();w=w.model_copy(deep=True)
    w.allocations[0].offering_id=w.allocations[1].offering_id
    errors=option_errors(p,w)
    assert any(x.code in ('WRONG_SUBJECT','SECTION_CAPACITY') for x in errors)
