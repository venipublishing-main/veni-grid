"""C5 synthetic authority record. Development only: NO real login or publishing."""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from hashlib import sha256
from datetime import datetime, timezone
import html, json

from scripts.run_c4_probes import crossed_multi_occurrence_fixture
from veni_grid_integration.c4_flexible_feedback import propose_c4
from veni_grid_contract.handoff_common import fingerprint
from veni_grid_authority import AuthorityStore, Principal, AuthorityFailure

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'c5-output'


def render_html(record):
    def esc(x):return html.escape(str(x),quote=True)
    events=record['events']
    items=''.join(
     f'<tr><td>{i+1}</td><td>{esc(e["action"].replace("_"," ").title())}</td>'
     f'<td>{esc(e["actor_id"].replace("user:",""))}</td>'
     f'<td>{esc(e["reason"])}</td><td>{e["new_revision"] if e["new_revision"] is not None else "—"}</td></tr>'
     for i,e in enumerate(events))
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Veni Grid C5 | Approval & version history</title><style>
:root{font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#1b3146;background:#f4f7fa}
*{box-sizing:border-box}body{margin:0}header{background:#162c43;color:#fff;padding:28px max(20px,calc((100vw - 1100px)/2))}
header small{letter-spacing:.17em;color:#83d4c7;font-weight:800}h1{font-size:clamp(26px,3vw,38px);letter-spacing:-.04em;margin:8px 0}header p{color:#b9cddd;max-width:800px;font-size:14px;line-height:1.6}
main{max-width:1100px;margin:auto;padding:26px 20px 60px}.banner{border:1px solid #b0d3d2;background:#eaf7f4;border-radius:12px;padding:14px 18px;font-size:13px;line-height:1.6;margin-bottom:18px}.banner strong{color:#087c70}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:20px}.metric,section{background:#fff;border:1px solid #dce5ee;border-radius:14px;padding:21px;box-shadow:0 3px 18px #1234a007}.metric small{color:#687d90;font-size:12px}.metric b{display:block;font-size:30px;letter-spacing:-.04em;margin-top:4px}
section{margin-bottom:18px}section h2{font-size:19px;margin:0 0 12px}section p{font-size:13px;color:#5c7385;line-height:1.7}.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}.step{border-radius:10px;background:#f1f5f8;padding:15px;border-left:4px solid #19877e;min-height:102px}.step b{font-size:13px;display:block}.step span{display:block;font-size:11px;color:#536c7f;line-height:1.5;margin-top:8px}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:12px;border-bottom:1px solid #e7edf2;font-size:12px;vertical-align:top}thead{background:#f5f8fa}tr:last-child td{border:0}.tablewrap{overflow:auto}.mono{font-family:ui-monospace,monospace;font-size:12px;background:#f0f4f8;padding:6px;border-radius:7px}
.actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}button{border:0;border-radius:9px;background:#dde5eb;color:#678093;padding:10px 15px;font-weight:750;cursor:not-allowed}.warning{border-left:4px solid #bd7d49;background:#fff6ee;padding:12px 16px;border-radius:8px;margin-top:14px;font-size:12px;line-height:1.6}
@media(max-width:700px){.grid{grid-template-columns:1fr 1fr}.steps{grid-template-columns:1fr 1fr}}
@media print{body{background:#fff}.actions{display:none}section,.metric{box-shadow:none}header{print-color-adjust:exact}}
</style></head><body>
<header><small>VENI GRID / C5 AUTHORITY REFERENCE</small><h1>Who approved this timetable version?</h1><p>A clear record of a proposed option-plan change, a separate approval and publication decision, and a reversible version history.</p></header>
<main><div class="banner"><strong>Development demonstration only.</strong> Every user and pupil is invented. These are real database transactions in a local SQLite test; no Veni Account sign-in, live school permission, external distribution or production publication occurred.</div>
<div class="grid"><div class="metric"><small>Original options version</small><b>1</b></div><div class="metric"><small>Approved revised version</small><b>2</b></div><div class="metric"><small>New restoration version</small><b>3</b></div></div>
<section><h2>What happened in the reference workflow?</h2><div class="steps"><div class="step"><b>1 · Proposal prepared</b><span>48 subject requests preserved and 18 moved. Separate planner permission required.</span></div><div class="step"><b>2 · Approved</b><span>Different authorised reviewer checks the original version and full C4 evidence.</span></div><div class="step"><b>3 · Published pointer</b><span>Separate explicit option-version publication. No other timetable changes.</span></div><div class="step"><b>4 · Restore and republish</b><span>Version 1 copied to NEW version 3. Historical version 2 remains immutable.</span></div></div>
<div class="warning"><b>Important:</b> This flow demonstrates server-side version semantics in a local reference store. It cannot authenticate a real school administrator and cannot publish a timetable to an app. The approval control below is deliberately disabled.</div></section>
<section><h2>Recorded version state</h2><p>The accepted working version and displayed publication pointer are separate. Rolling back never silently changes the published version.</p><p><span class="mono">Approved options revision: __HEAD__</span> <span class="mono">Publication pointer: __PUBLISHED__</span></p><p><b>Independent academic teaching timetable:</b> NOT APPROVED OR PUBLISHED. Examinations, invigilation, duties and sport are independent.</p></section>
<section><h2>Append-only audit trail</h2><p>Each operation records an actor, an action, an explicit reason, the version and a chained SHA-256 receipt. This protects against accidental rewrites in this reference; production will need stronger database-level permissions and logging controls.</p><div class="tablewrap"><table><thead><tr><th>#</th><th>Event</th><th>Actor</th><th>Reason</th><th>Version</th></tr></thead><tbody>__EVENTS__</tbody></table></div></section>
<section><h2>Security and actions</h2><div class="actions"><button disabled>Approve — login integration required</button><button disabled>Publish — service integration required</button><button disabled>Restore — service integration required</button></div><p>No click here can modify a database, school timetable or shared Veni account. These are intentionally inert demonstration controls.</p></section></main></body></html>'''.replace('__EVENTS__',items).replace('__HEAD__',str(record['state']['revision'])).replace('__PUBLISHED__',str(record['state']['published_revision']))


def run():
    OUT.mkdir(exist_ok=True)
    req=crossed_multi_occurrence_fixture()
    proposal=propose_c4(req)
    if proposal.status!='PROPOSED_VALIDATED' or proposal.review is None:
        raise RuntimeError(f'C4 preview cannot be accepted into reference: {proposal.status}')
    owner=Principal('org:synthetic','user:owner')
    planner=Principal('org:synthetic','user:planner')
    checker=Principal('org:synthetic','user:checker')
    publisher=Principal('org:synthetic','user:publisher')
    restorer=Principal('org:synthetic','user:restorer')
    sid=req.current.source_ref.schedule_id
    with TemporaryDirectory(prefix='grid-c5-ref-') as tmp:
        store=AuthorityStore(Path(tmp)/'authority.sqlite',development_bootstrap=True)
        store.bootstrap(owner,sid,req.current.source)
        for actor,permission in [(planner,'propose'),(checker,'approve'),
                                 (publisher,'publish'),(restorer,'restore')]:
            store.add_member(owner,actor.subject_id,reason='Synthetic staff role provisioning')
            store.grant(owner,sid,actor.subject_id,permission,reason='Explicit school scheduling privilege')
            store.grant(owner,sid,actor.subject_id,'view',reason='Allow version and review access')
        current=store.get_state(owner,sid)
        staged=store.stage_c4(planner,sid,'proposal:lesson-revision',req,proposal,
                reason='Offer an independently checked alternative plan',idem_key='c5-stage-sample-001')
        if store.get_state(owner,sid)['revision']!=1:raise RuntimeError('Preview mutated accepted head')
        approved=store.approve_c4(checker,sid,'proposal:lesson-revision',
                 expected_revision=1,reason='Reviewed pupil changes and teaching resources',idem_key='c5-approve-sample-001')
        if approved['approved_revision']!=2 or approved['published_revision'] is not None:
            raise RuntimeError('Approval improperly changed publication')
        first_publish=store.publish_current(publisher,sid,expected_revision=2,
               reason='Publish accepted option version two only',idem_key='c5-publish-sample-001')
        reverted=store.restore(restorer,sid,1,expected_revision=2,
               reason='Restore original option plan for comparison',idem_key='c5-restore-sample-001')
        if reverted['revision']!=3 or reverted['published_revision']!=2:
            raise RuntimeError('Rollback unexpectedly changed published version')
        final_publish=store.publish_current(publisher,sid,expected_revision=3,
               reason='Explicitly republish restored option revision',idem_key='c5-publish-sample-002')
        state=store.get_state(owner,sid)
        audit=store.audit_trail(owner,sid)
        if not store.verify_audit(owner,sid):raise RuntimeError('Audit hash chain broken')
        if store.get_version(owner,sid,1)['hash']!=store.get_version(owner,sid,3)['hash']:
            raise RuntimeError('Restoration did not restore immutable source')
        if state['revision']!=3 or state['published_revision']!=3:
            raise RuntimeError('No explicit option publication update')
        report={'kind':'C5_SQLITE_DEVELOPMENT_REFERENCE','synthetic_only':True,
          'authentication':'NOT_IMPLEMENTED','real_authorisation':'NOT_CONNECTED',
          'source_revision':current['revision'],'source_hash':current['hash'],
          'proposal_status':staged['state'],'staged_without_head_change':True,
          'approved_revision':approved['approved_revision'],
          'first_published_revision':first_publish['published_revision'],
          'restore_revision':reverted['revision'],
          'published_revision_after_restore_before_republish':reverted['published_revision'],
          'final_published_revision':final_publish['published_revision'],
          'audit_chain_valid':True,'audit_entries':len(audit),
          'maker_checker_enforced':True,'source_still_immutable':True,
          'original_c4_result':{'preserved_requests':proposal.review.preserved_compulsory_requests,
             'changed_request_count':len(proposal.review.changed_request_ids),
             'proposed_sections':proposal.review.after_section_count,
             'independent_teaching_events':proposal.review.after_teaching_events},
          'scope':'ACADEMIC_OPTIONS_ONLY','academic_timetable_published':False,
          'other_schedule_changes':'NONE','external_distribution':'NOT_IMPLEMENTED',
          'state':state,
          'events':[{k:e[k] for k in ('action','actor_id','reason','previous_revision','new_revision','event_hash')}
                    for e in audit]}
        (OUT/'c5-reference-summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        (OUT/'c5-approval-history.html').write_text(render_html(report),encoding='utf-8')
        store.close()
    print(json.dumps({k:v for k,v in report.items() if k not in ('events','source_hash')},indent=2))
    return report

if __name__=='__main__':run()
