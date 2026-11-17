"""C9 local guardrails: static only, no claim of real Supabase integration."""
from pathlib import Path
from veni_grid_authority.c9_server_bridge import C9ServerBridge,ServerScheduleRegistration
import inspect,pytest
ROOT=Path(__file__).resolve().parents[1]


def test_c9_has_no_http_api_or_live_project_configuration():
    path=ROOT/'veni_grid_authority/c9_server_bridge.py';text=path.read_text()
    assert 'class C9ServerBridge' in text and 'review_errors(' in text
    assert 'supabase.co' not in text and 'service_role' not in text
    assert 'FastAPI(' not in text and 'Flask(' not in text


def test_bridge_accepts_only_server_selected_schedule_key_not_client_org():
    sig=inspect.signature(C9ServerBridge.stage_reviewed_c4)
    assert 'schedule_key' in sig.parameters
    assert 'organisation_id' not in sig.parameters and 'user_id' not in sig.parameters


def test_trusted_registration_rejects_noncanonical_uuid():
    with pytest.raises(ValueError):ServerScheduleRegistration('x','org:forged','id:schedule','x','y','0'*64)


def test_c9_disposable_pg_security_remains_out_of_supabase_migrations():
    p=ROOT/'db/c8/c8_isolated_policy_approval.sql'
    assert p.is_file() and (ROOT/'db/review/c6_grid_private_schema.sql').is_file()
    assert not (ROOT/'supabase/migrations').exists()


def test_no_client_publishing_or_implicit_academic_scheduling():
    text=(ROOT/'veni_grid_authority/c9_server_bridge.py').read_text()
    assert 'publish_current' not in text and 'SET LOCAL ROLE' in text
    assert 'ACADEMIC_OPTIONS' in text and 'NOT_GRANTED' in text
