"""Only fabricated options, UUIDs and fingerprints. No live school records."""
from uuid import uuid4

import pytest

from scripts.run_c4_probes import crossed_multi_occurrence_fixture
from veni_grid_contract.handoff_common import fingerprint
from veni_grid_authority.c11_evidence import SourceBinding, create_evidence


@pytest.fixture(scope="module")
def example():
    original = crossed_multi_occurrence_fixture().current.source
    binding = SourceBinding(
        organisation_uuid=str(uuid4()), schedule_uuid=str(uuid4()),
        source_revision=1, source_grid_json_1_sha256=fingerprint(original),
        c4_validated_teaching_sha256="a" * 64,
    )
    return original, binding, create_evidence(original, binding=binding)
