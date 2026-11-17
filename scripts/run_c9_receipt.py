"""Re-execute real signed-token -> C4 independent checker -> PG C8 approval.

Synthetic-only; uses C9 test fixture builder on disposable GitHub PostgreSQL 17.
Never creates an API, contacts Supabase, or archives keys/tokens/identifiers.
"""
from __future__ import annotations
import json,os,html
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'c9-output'

def run():
    if os.environ.get('GRID_C7_DISPOSABLE_ONLY')!='YES' or os.environ.get('GRID_C8_DISPOSABLE_ONLY')!='YES' or os.environ.get('GRID_C9_DISPOSABLE_ONLY')!='YES':
        raise RuntimeError('C9 requires explicit disposable PG test gates')
    from psycopg.conninfo import conninfo_to_dict,make_conninfo
    from psycopg import connect
    base=os.environ.get('GRID_C7_PG_DSN','')
    if not base:raise RuntimeError('No C7 PG service DSN')
    args=conninfo_to_dict(base)
    if args.get('dbname')!='grid_c7_isolated' or args.get('host') not in ('localhost','127.0.0.1'):
        raise RuntimeError('C9 refuses hosted or unknown PG connection')
    dsn=make_conninfo(base,dbname='grid_c8_isolated')
    with connect(dsn) as db:
        name,role,ver=db.execute("SELECT current_database(),current_user,current_setting('server_version_num')::int").fetchone()
        assert name=='grid_c8_isolated' and role=='postgres' and 170000<=ver<180000
    from scripts.run_c4_probes import crossed_multi_occurrence_fixture
    from veni_grid_integration.c4_flexible_feedback import propose_c4
    from c9_tests.conftest import c9_school,stage,approve
    req=crossed_multi_occurrence_fixture();proposed=propose_c4(req)
    if proposed.status!='PROPOSED_VALIDATED' or proposed.review is None:
        raise RuntimeError('C9 cannot stage an unvalidated C4 candidate')
    # The pytest fixture is a synthetic data factory; __wrapped__ invokes only
    # its original test body, with no actual Supabase user/session/API.
    fixture=c9_school.__wrapped__({'dsn':dsn},(req,proposed))
    created=stage(fixture)
    fixture['proposal']=created['proposal_id']
    response=approve(fixture)
    with connect(dsn) as db:
        stored=db.execute('SELECT head_revision,published_revision FROM grid_private.schedules WHERE organisation_id=%s AND id=%s',
                         (fixture['org'],fixture['sid'])).fetchone()
        snapshot=db.execute('SELECT snapshot FROM grid_private.accepted_versions WHERE organisation_id=%s AND schedule_id=%s AND revision=2',
                            (fixture['org'],fixture['sid'])).fetchone()[0]
        staged=db.execute("SELECT count(*) FROM grid_private.audit_events WHERE organisation_id=%s AND schedule_id=%s AND action='C9_PROPOSAL_STAGED'",(fixture['org'],fixture['sid'])).fetchone()[0]
        accepted=db.execute("SELECT count(*) FROM grid_private.audit_events WHERE organisation_id=%s AND schedule_id=%s AND action='PROPOSAL_APPROVED'",(fixture['org'],fixture['sid'])).fetchone()[0]
    assert created['status']=='PENDING' and created['independently_validated']
    assert response['status']=='APPROVED' and stored==(2,None)
    assert len(snapshot['plan']['offerings'])==9 and len(snapshot['plan']['allocations'])==48
    assert staged==accepted==1
    summary={
      'kind':'C9_SYNTHETIC_CRYPTO_C4_POSTGRES_GATE',
      'signed_access_token':'VERIFIED_OFFLINE_RSA_SIGNATURE',
      'session_status':'TEST_CALLBACK_ACTIVE_THEN_CHECKED',
      'school_membership':'ACTUAL_DISPOSABLE_POSTGRES_LOOKUP',
      'schedule_permission':'PROPOSE_AND_APPROVE_RECHECKED_IN_POSTGRES',
      'source_registry':'TRUSTED_TEST_REGISTRATION_NOT_JWT_METADATA',
      'independent_c4_review':'PASSED',
      'compulsory_requests_preserved':proposed.review.preserved_compulsory_requests,
      'moved_requests':len(proposed.review.changed_request_ids),
      'section_count':len(snapshot['plan']['offerings']),
      'independently_validated_teaching_events':proposed.preview_c2.event_count,
      'staged_status':created['status'],'approved_status':response['status'],
      'new_accepted_options_revision':stored[0],'published_options_revision':stored[1],
      'audit_stage_events':staged,'audit_approval_events':accepted,
      'current_live_auth':'NOT_CONNECTED','real_mfa_oracle':'NOT_CONNECTED',
      'staging_database_migration':'NOT_APPLIED',
      'postgres_connection':'DISPOSABLE_PG17_WITH_TEST_SUPERUSER',
      'C8_actor_context':'SERVER_SET_NOT_CRYPTOGRAPHIC_AUTH',
      'external_publication':'NOT_GRANTED',
      'actual_school_data':'NONE'
    }
    OUT.mkdir(exist_ok=True)
    (OUT/'c9-verified-reference.json').write_text(json.dumps(summary,indent=2)+'\n')
    carddata=[
       ('1 · Who is this?','Real signed-token verification using invented keys, with a current-session test callback.'),
       ('2 · Which school?','The school is selected by the server registry, and active membership is checked from PostgreSQL.'),
       ('3 · Is the proposal genuine?','The original C4 checker independently validates 48 choices, nine sections and 18 teaching events before a proposal is stored.'),
       ('4 · Who approves?','A different verified, MFA-assured test identity must hold the exact approval grant; the database rechecks it.'),
       ('5 · What changed?','One approved option-plan revision is created; the published pointer remains empty. No other timetable changes.'),
       ('Not production','Sessions, role credentials, staging identities and external delivery remain test-only.')]
    cards=''.join(f'<article><strong>{html.escape(x)}</strong><p>{html.escape(y)}</p></article>' for x,y in carddata)
    page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Veni Grid C9 verified staging</title><style>
body{{margin:0;color:#182f43;background:#f5f7fa;font-family:system-ui,Segoe UI,sans-serif}}header{{padding:38px max(24px,calc((100vw - 1100px)/2));background:#172e46;color:#fff}}header small{{color:#85d7c5;font-weight:800;letter-spacing:.1em}}h1{{font-size:clamp(25px,3vw,39px);margin:9px 0}}header p{{color:#c9d9e5;max-width:740px;line-height:1.6}}main{{max-width:1100px;margin:auto;padding:25px}}.metrics,.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.metrics{{margin-bottom:24px}}.metric,article{{padding:20px;background:#fff;border-radius:13px;border:1px solid #dbe5ee}}.metric b{{display:block;font-size:32px}}.metric span{{font-size:12px;color:#587287}}.cards{{grid-template-columns:repeat(2,1fr)}}article strong{{font-size:15px}}article p{{font-size:13px;color:#607588;line-height:1.6}}.warn{{margin:20px 0;padding:18px;background:#fff3e8;border-left:4px solid #b77e44;border-radius:9px;font-size:13px;line-height:1.6}}footer{{font-size:12px;color:#708599;padding:7px}}@media(max-width:680px){{.metrics,.cards{{grid-template-columns:1fr}}}}</style></head><body><header><small>VENI GRID · C9 TRUSTED SERVER REFERENCE</small><h1>A checked proposal, approved by a different person.</h1><p>The first integrated signed-identity → school membership → C4 mathematical review → PostgreSQL acceptance demonstration.</p></header><main><div class="metrics"><div class="metric"><b>48/48</b><span>Learner choices preserved</span></div><div class="metric"><b>18</b><span>Real teaching occurrences validated</span></div><div class="metric"><b>2</b><span>New approved options revision (not published)</span></div></div><div class="cards">{cards}</div><div class="warn"><b>Still a laboratory demonstration.</b> These are invented accounts and a disposable local PostgreSQL database. No live Veni Account session or MFA system, authentic school registry, production database, API, approval button, separate academic-lesson publication, or external distribution is enabled.</div><footer>All signing keys, JWTs, database usernames and test school identifiers remain out of the archived result.</footer></main></body></html>'''
    (OUT/'c9-verified-reference.html').write_text(page)
    print(json.dumps({k:v for k,v in summary.items() if 'source' not in k},indent=2))
    return summary
if __name__=='__main__':run()
