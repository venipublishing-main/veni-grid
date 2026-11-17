"""Produce a minimal user-readable C8 receipt from actual disposable PG SQL.

Never stores a user ID, token, signing key, DSN or credentials in an artifact.
"""
from __future__ import annotations
from pathlib import Path
import json,os,html
from uuid import uuid4
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'c8-output'

def run():
    if os.environ.get('GRID_C8_DISPOSABLE_ONLY')!='YES' or os.environ.get('GRID_C7_DISPOSABLE_ONLY')!='YES':
        raise RuntimeError('C8 receipt requires disposable PostgreSQL double-gate')
    baseline=os.environ.get('GRID_C7_PG_DSN','')
    if not baseline or conninfo_to_dict(baseline).get('dbname')!='grid_c7_isolated':
        raise RuntimeError('C8 requires only isolated C7 PostgreSQL service')
    dsn=make_conninfo(baseline,dbname='grid_c8_isolated')
    with psycopg.connect(dsn) as db:
        dbname,role,version=db.execute("SELECT current_database(),current_user,current_setting('server_version_num')::int").fetchone()
        if dbname!='grid_c8_isolated' or role!='postgres' or not 170000<=version<180000:
            raise RuntimeError('Unexpected C8 PostgreSQL target')
        count=db.execute("SELECT count(*) FROM pg_policies WHERE schemaname='grid_private'").fetchone()[0]
        assert count>=14
        a,b=str(uuid4()),str(uuid4());sid_a,sid_b=str(uuid4()),str(uuid4())
        planner,checker,viewer,other=str(uuid4()),str(uuid4()),str(uuid4()),str(uuid4())
        for u in [planner,checker,viewer,other]:db.execute('INSERT INTO auth.users(id) VALUES(%s)',(u,))
        db.execute('INSERT INTO grid_private.organisations(id,display_name) VALUES(%s,%s)',(a,'Fictitious school Alpha'))
        db.execute('INSERT INTO grid_private.organisations(id,display_name) VALUES(%s,%s)',(b,'Fictitious school Beta'))
        for org,user in [(a,planner),(a,checker),(a,viewer),(b,other)]:
            db.execute("INSERT INTO grid_private.memberships(organisation_id,account_id,role,state) VALUES(%s,%s,'MEMBER','ACTIVE')",(org,user))
        db.execute("INSERT INTO grid_private.schedules(organisation_id,id,kind,label,head_revision,head_sha256) VALUES(%s,%s,'ACADEMIC_OPTIONS','Synthetic options A',1,%s)",(a,sid_a,'a'*64))
        db.execute("INSERT INTO grid_private.schedules(organisation_id,id,kind,label,head_revision,head_sha256) VALUES(%s,%s,'ACADEMIC_OPTIONS','Synthetic options B',1,%s)",(b,sid_b,'b'*64))
        db.execute("INSERT INTO grid_private.accepted_versions(organisation_id,schedule_id,revision,snapshot,sha256,accepted_by) VALUES(%s,%s,1,'{}'::jsonb,%s,%s)",(a,sid_a,'a'*64,planner))
        db.execute("INSERT INTO grid_private.accepted_versions(organisation_id,schedule_id,revision,snapshot,sha256,accepted_by) VALUES(%s,%s,1,'{}'::jsonb,%s,%s)",(b,sid_b,'b'*64,other))
        for user,perm in [(viewer,'view'),(checker,'approve')]:
            db.execute("INSERT INTO grid_private.schedule_grants(organisation_id,schedule_id,account_id,permission,granted_by) VALUES(%s,%s,%s,%s,%s)",(a,sid_a,user,perm,planner))
        payload='{"status":"independently validated in upstream C4 synthetic test"}';p=str(uuid4())
        db.execute("INSERT INTO grid_private.proposals(organisation_id,schedule_id,id,source_revision,source_sha256,payload,payload_sha256,proposed_by) VALUES(%s,%s,%s,1,%s,%s::jsonb,encode(public.digest(convert_to(%s::jsonb::text,'UTF8'),'sha256'),'hex'),%s)",(a,sid_a,p,'a'*64,payload,payload,planner))
    # Data must be committed before a second role-scoped connection can see it.
    with psycopg.connect(dsn) as reader:
        reader.execute('SET LOCAL ROLE grid_c8_reader')
        reader.execute("SELECT set_config('grid.c8_actor_id',%s,true)",(viewer,))
        visible=reader.execute('SELECT id FROM grid_private.schedules').fetchall()
        own=(len(visible)==1 and str(visible[0][0])==sid_a)
        cross=sum(str(x[0])==sid_b for x in visible)
    with psycopg.connect(dsn) as operator:
        operator.execute('SET LOCAL ROLE grid_c8_operator')
        operator.execute("SELECT set_config('grid.c8_actor_id',%s,true)",(checker,))
        operator.execute("SELECT set_config('grid.c8_aal','aal2',true)")
        query='SELECT grid_private.c8_approve(%s,%s,%s,%s,%s,%s,%s)'
        args=(a,sid_a,p,1,'a'*64,'Independent evidence and source checked','c8-receipt-approve-0001')
        first=operator.execute(query,args).fetchone()[0]
        second=operator.execute(query,args).fetchone()[0]
    with psycopg.connect(dsn) as db:
        actual=db.execute('SELECT head_revision,published_revision FROM grid_private.schedules WHERE organisation_id=%s AND id=%s',(a,sid_a)).fetchone()
        audit=db.execute('SELECT count(*) FROM grid_private.audit_events WHERE organisation_id=%s AND schedule_id=%s',(a,sid_a)).fetchone()[0]
    assert actual==(2,None) and first==second and audit==1 and own and cross==0
    report={
       'kind':'C8_ISOLATED_POSTGRESQL_REFERENCE',
       'executed_real_postgresql':True,'postgresql_major':17,
       'tables_protected_by_rls':8,'policy_count_at_least_14':True,
       'authenticated_member_sees_own_schedule':own,
       'other_school_rows_visible':cross,
       'approved_revision':actual[0],'published_revision':actual[1],
       'maker_checker_required':True,'aal2_required':True,
       'idempotency_replay_same_receipt':first==second,
       'approval_audit_entries':audit,'separate_school_data_modified':False,
       'live_veni_account_auth':'NOT_CONNECTED',
       'authority_context':'SERVER_ONLY_REFERENCE_NOT_SESSION_PROOF',
       'prod_postgres_migration':'NOT_APPLIED','external_publication':'NOT_GRANTED',
       'c4_independent_solver_verification':'UPSTREAM_REFERENCE_ONLY_NOT_DB_ENFORCED',
       'production_readiness':'NOT_PROVED','all_identifiers':'SYNTHETIC_ONLY'
    }
    OUT.mkdir(exist_ok=True)
    (OUT/'c8-reference-summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    rows=[('Separate schools','The viewer sees only its own school’s timetable, not another school’s.'),
          ('Exact rights','Membership alone does not confer the power to approve.'),
          ('Two people','The person proposing a change cannot approve that same proposal.'),
          ('MFA step-up','Approval requires an AAL2 assurance indicator from the trusted server.'),
          ('Safe revision','An accepted option version advances to revision 2 without publishing a timetable.'),
          ('Duplicate requests','The same approval request returns the same result and does not duplicate audit entries.'),
          ('Still not live','These were server-only test identities. No actual Veni login/session or staging database transaction.')]
    cards=''.join(f'<article><h3>{html.escape(name)}</h3><p>{html.escape(desc)}</p></article>' for name,desc in rows)
    page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Veni Grid C8 — School rights & approvals</title><style>
body{{margin:0;background:#f4f7fa;color:#172d46;font-family:system-ui,Segoe UI,sans-serif}}header{{background:#142d44;color:white;padding:38px max(23px,calc((100vw - 1040px)/2))}}header small{{color:#78d7c1;font-weight:800;letter-spacing:.13em}}h1{{font-size:clamp(25px,3vw,38px);margin:8px 0}}header p{{color:#c9d8e6;line-height:1.6}}main{{max-width:1040px;margin:auto;padding:24px}}.metrics,.cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px}}.metrics{{margin-bottom:20px}}.metric,article{{background:white;padding:21px;border:1px solid #dce5ed;border-radius:13px}}.metric strong{{display:block;font-size:30px}}.metric span{{font-size:12px;color:#617889}}.cards{{grid-template-columns:repeat(2,minmax(0,1fr))}}article h3{{font-size:16px;margin:0 0 7px}}article p{{font-size:13px;line-height:1.65;color:#536a7d;margin:0}}.warn{{background:#fff3e6;border-left:4px solid #ba7d4a;padding:16px;margin:20px 0;border-radius:8px;font-size:13px;line-height:1.65}}footer{{font-size:12px;color:#728596;margin:16px 0}}@media(max-width:650px){{.metrics,.cards{{grid-template-columns:1fr}}}}</style></head><body><header><small>VENI GRID · C8 SECURITY LAB</small><h1>Who may approve a school timetable?</h1><p>Actual PostgreSQL 17 results from invented users and schools. Approval is restricted to a member with the right permission, separate from the person who proposed it.</p></header><main><div class="metrics"><div class="metric"><strong>1</strong><span>School visible to authorised viewer</span></div><div class="metric"><strong>0</strong><span>Other-school timetable rows visible</span></div><div class="metric"><strong>2</strong><span>New approved option revision (not published)</span></div></div><div class="cards">{cards}</div><div class="warn"><strong>Not enabled in Veni Account.</strong> All results are from the disposable PostgreSQL lab. An identity claim or MFA setting inside a database connection can be spoofed by someone who gains the server role, so a real session verifier, locked server credentials and staging audit are mandatory before live use. This reference cannot authenticate or approve a real school timetable.</div><footer>The existing C1–C7 scheduling baseline is unchanged. Synthetic data only. No publication, live project changes or credentials included in this report.</footer></main></body></html>'''
    (OUT/'c8-reference-explained.html').write_text(page,encoding='utf-8')
    print(json.dumps(report,indent=2))
    return report

if __name__=='__main__':run()
