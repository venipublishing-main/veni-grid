"""Human-readable, validated C4 change review; every lesson from the real C2 candidate.

No approval handler, persistence, account credentials or invented schedule times.
"""
from __future__ import annotations
import html,json,re
from pathlib import Path
from scripts.render_c2_for_people import make_payload,render_html


def _esc(x):return html.escape(str(x),quote=True)
def _block_label(id):
    try:return f'Option block {int(id.rsplit("B",1)[-1])+1}'
    except (ValueError,IndexError):return 'Option block (unlabelled)'


def render(request, result, out:Path):
    if result.status!='PROPOSED_VALIDATED' or not result.review or not result.preview_c2:
        raise ValueError('Only an independently checked C4 preview may be displayed as valid')
    from veni_grid_integration.c4_flexible_feedback import review_errors
    issues=review_errors(request.current,result.proposed_o1,result.preview_c2,result.review)
    if issues:raise ValueError('Review verification failed: '+','.join(issues))
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    problem=result.preview_c2.placement_problem.model_dump(mode='json')
    candidate=result.preview_c2.candidate.model_dump(mode='json')
    payload=make_payload(problem,candidate)
    if payload['count']!=result.review.after_teaching_events:raise ValueError('Missing teaching events')
    timetable=render_html(payload)
    (out/'c4-proposed-teaching-timetable.html').write_text(timetable,encoding='utf-8')
    report=result.review
    rows=[]
    for family in report.changes:
        def blocks(items):return ', '.join(_block_label(b) for b in items)
        subject='Subject '+family.subject.replace('Invented ','')
        old=blocks(family.before_blocks);new=blocks(family.after_blocks)
        cls='changed' if family.before_blocks!=family.after_blocks or family.before_sections!=family.after_sections else ''
        rows.append(f'<tr class="{cls}"><th scope="row">{_esc(subject)}</th><td>{_esc(old)}<small>{family.before_sections} sections</small></td><td>{_esc(new)}<small>{family.after_sections} sections</small></td><td>{family.changed_requests}</td></tr>')
    classes=[]
    for item in payload['lesson_records']:
        # C2 synthetic names, selected rooms and minutes come from the independent witness.
        token=_esc(item['day']);teach=_esc(item['teacher']);room=_esc(item['room'])
        tag='Double laboratory lesson' if item['double'] and item['lab'] else ('Double lesson' if item['double'] else 'Single lesson')
        day_label='Day '+item['day'].rsplit('D',1)[-1].lstrip('0')
        classes.append(f'<article class="lesson" data-day="{token}" data-teacher="{teach}" data-room="{room}"><div class="lesson-top"><strong>{_esc(item["subject"])}</strong><span>{_esc(day_label)} · {_esc(item["time_label"])}</span></div><p>{_esc(item["class"])} · {item["pupils"]} learners</p><div class="lesson-bottom"><span>👩‍🏫 {_esc(item["teacher"])}</span><span>🏫 {room}</span><span>{_esc(tag)}</span></div></article>')
    select_teacher=''.join(f'<option value="{_esc(t)}">{_esc(t)}</option>' for t in payload['teachers'])
    select_room=''.join(f'<option value="{_esc(r)}">{_esc(r)}</option>' for r in payload['rooms'])
    reason='; '.join(result.old_c2_findings[:2]).replace('BLOCK_TEACHER_SHORTAGE:','Not enough suitably qualified teachers for simultaneous classes:').replace('BLOCK_CLASSROOM_SHORTAGE:','Not enough suitable rooms for simultaneous classes:')
    reason=re.sub(r'block:B(\d+)/occ:D(\d+)',lambda m:f'Option block {int(m.group(1))+1} on Day {int(m.group(2))}',reason)
    markup='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Veni Grid | Review an alternative timetable</title>
<style>
:root{font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;background:#f3f6fa;color:#182d43;--line:#dbe4ed;--teal:#0c827a}*{box-sizing:border-box}body{margin:0}button,select{font:inherit}header{background:#142b43;color:#fff;padding:30px max(24px,calc((100vw - 1160px)/2));}header .eyebrow{letter-spacing:.17em;color:#85d2ca;font-size:11px;font-weight:800}header h1{margin:8px 0;font-size:clamp(23px,3vw,34px);letter-spacing:-.035em}header p{margin:4px 0;color:#c2d2df;font-size:13px;line-height:1.6}main{max-width:1160px;padding:24px;margin:auto}section{background:#fff;border-radius:15px;border:1px solid var(--line);margin-bottom:18px;padding:23px}section h2{font-size:19px;margin:0 0 12px;letter-spacing:-.025em}section p{color:#536b7d;line-height:1.6;font-size:13px}.caution{background:#edf6f3;border-left:4px solid #168679;border-radius:10px;padding:15px 18px;line-height:1.5;font-size:13px;margin:18px 0}.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:18px}.stat{background:white;border:1px solid var(--line);padding:18px;border-radius:12px}.stat strong{display:block;font-size:27px}.stat span{font-size:12px;color:#63788b}.columns{display:grid;grid-template-columns:1fr 1fr;gap:16px}.before{background:#fff4f0;border-radius:12px;padding:17px;border-left:4px solid #c57258}.after{background:#eaf8f2;border-radius:12px;padding:17px;border-left:4px solid #219475}.columns b{display:block;margin-bottom:5px}.columns p{margin:6px 0}.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:670px}th,td{text-align:left;border-bottom:1px solid #edf0f4;padding:13px 12px;font-size:13px}thead{background:#f4f7fa}tr.changed td, tr.changed th{background:#f3faf8}td small{display:block;color:#728597;margin-top:4px}th[scope=row]{font-weight:750}.controls{display:flex;flex-wrap:wrap;align-items:end;gap:10px;margin-bottom:16px}.controls label{font-size:12px;color:#597083;display:flex;flex-direction:column;gap:5px}select{padding:9px 11px;border:1px solid #ccd8e3;border-radius:9px;background:#fff;min-width:160px}.lessons{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.lesson{padding:15px;border:1px solid #dbe6ed;border-left:4px solid #25968c;border-radius:11px;background:#fbfefe}.lesson-top{display:flex;justify-content:space-between;gap:8px;font-size:13px}.lesson-top span{white-space:nowrap;color:#147f75}.lesson p{margin:10px 0;font-size:12px}.lesson-bottom{display:grid;gap:6px;color:#466176;font-size:12px}.status{background:#f8fafc;padding:14px;border-radius:9px;margin-top:16px;font-size:12px;color:#4c6578}.actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.btn{display:inline-block;border:1px solid #c9d8e1;background:#fff;color:#195e67;border-radius:9px;padding:11px 14px;font-size:12px;font-weight:750;text-decoration:none;cursor:pointer}.btn.disabled{color:#738493;background:#e7ebef;border-color:#e7ebef;cursor:not-allowed}.empty{font-size:13px;color:#667d8b;padding:14px}.foot{font-size:12px;color:#718395;line-height:1.7}@media(max-width:900px){.lessons{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){.stats{grid-template-columns:repeat(2,1fr)}.columns{grid-template-columns:1fr}.lessons{grid-template-columns:1fr}main{padding:13px}}
@media print{header{print-color-adjust:exact}body{background:white}.controls,.actions{display:none}.lesson{break-inside:avoid}section{break-inside:avoid}}
</style></head><body><header><div class="eyebrow">VENI GRID · SCHEDULING REVIEW</div><h1>We found a different way to schedule these classes.</h1><p>A real, independently verified alternative. You can inspect it, but it has not been accepted or published.</p></header>
<main><div class="caution"><strong>Draft proposal only.</strong> Both the original option plan and the new proposal use invented people, subjects and classrooms. A real school would need an authenticated reviewer, a current-version check and a separate publication action.</div>
<div class="stats"><div class="stat"><strong>__REQUESTS__</strong><span>Learner subject choices preserved</span></div><div class="stat"><strong>__CHANGED__</strong><span>Subject choices moved to a different option block</span></div><div class="stat"><strong>__SECTIONS__</strong><span>Proposed class sections</span></div><div class="stat"><strong>__LESSONS__</strong><span>Independently verified teaching lessons</span></div></div>
<section><h2>Why was a different plan needed?</h2><div class="columns"><div class="before"><b>First plan — could not be taught</b><p>__OLD_REASON__</p><p>__BEFORE_COUNT__ sections had been created.</p></div><div class="after"><b>New plan — valid in preview</b><p>Grid redistributed some learners between option blocks, rebuilt the sections, and checked the actual teacher, room and lesson assignments.</p><p>Every compulsory subject choice remains intact.</p></div></div></section>
<section><h2>What has changed?</h2><p>The highlighted rows show where classes or option blocks changed. "Moved choices" counts individual learner-subject requests, not people.</p><div class="tablewrap"><table><thead><tr><th>Subject</th><th>First plan</th><th>Proposed plan</th><th>Moved choices</th></tr></thead><tbody>__DIFF_ROWS__</tbody></table></div></section>
<section><h2>Proposed teaching timetable</h2><p>These are the <strong>actual lesson placements</strong> from the independently validated C2 solver, not illustrative boxes.</p><div class="controls"><label>Cycle day<select id="day"><option value="ALL">Both days</option><option value="day:D1">Day 1</option><option value="day:D2">Day 2</option></select></label><label>Teacher<select id="teacher"><option value="ALL">All teachers</option>__TEACHER_OPTIONS__</select></label><label>Classroom<select id="room"><option value="ALL">All classrooms</option>__ROOM_OPTIONS__</select></label></div><div class="lessons" id="lessons">__LESSON_CARDS__</div><div class="empty" id="none" hidden>No lessons match the selected filters.</div><p class="status" id="visible">All validated lessons shown.</p></section>
<section><h2>What happens next?</h2><p>There is deliberately <strong>no approval or publication action</strong> in this standalone demo. Those actions require an authenticated, permission-checked server and an atomic current-version check.</p><div class="actions"><a class="btn" href="c4-proposed-teaching-timetable.html">Open full class timetable</a><button class="btn" id="print" type="button">Print review</button><button class="btn disabled" type="button" disabled aria-label="Approval unavailable until secure server integration">Approve — secure service required</button></div></section><p class="foot">Scope: 16 synthetic learners, 4 invented subjects, 2 cycle-day occurrences, one science-style double lesson per day. No learner database, organisation roles, live schedule editing, final acceptance or publishing.</p></main>
<script>const $$=id=>document.getElementById(id);function apply(){let n=0;for(const e of document.querySelectorAll('.lesson')){const match=['day','teacher','room'].every(id=>$$(id).value==='ALL'||e.dataset[id]===$$(id).value);e.hidden=!match;if(match)n++}$$('none').hidden=n>0;$$('visible').textContent=n+' validated lesson'+(n===1?'':'s')+' shown';}for(const id of ['day','teacher','room'])$$(id).addEventListener('change',apply);$$('print').addEventListener('click',()=>window.print());apply();</script></body></html>'''
    values={'__REQUESTS__':str(report.preserved_compulsory_requests),
        '__CHANGED__':str(len(report.changed_request_ids)),
        '__SECTIONS__':str(report.after_section_count),
        '__LESSONS__':str(report.after_teaching_events),
        '__BEFORE_COUNT__':str(report.before_section_count),
        '__OLD_REASON__':_esc(reason),
        '__DIFF_ROWS__':''.join(rows),'__TEACHER_OPTIONS__':select_teacher,
        '__ROOM_OPTIONS__':select_room,'__LESSON_CARDS__':''.join(classes)}
    for k,v in values.items():markup=markup.replace(k,v)
    (out/'c4-review-before-after.html').write_text(markup,encoding='utf-8')
    (out/'c4-review-receipt.json').write_text(report.model_dump_json(indent=2)+'\n',encoding='utf-8')
    return payload

if __name__=='__main__':
    from scripts.run_c4_probes import crossed_multi_occurrence_fixture
    from veni_grid_integration.c4_flexible_feedback import propose_c4
    req=crossed_multi_occurrence_fixture();res=propose_c4(req)
    if res.status!='PROPOSED_VALIDATED':raise RuntimeError(res.findings)
    out=Path(__file__).resolve().parents[1]/'c4-output';render(req,res,out)
    print(out/'c4-review-before-after.html')
