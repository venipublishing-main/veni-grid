"""Render a real, hard-validated synthetic C2 candidate into a layperson-readable timetable.

Input is the C2 model and its actual CP-SAT witness. No invented placement
or client-side optimisation. Outputs self-contained HTML and a provenance JSON.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from pathlib import Path
import hashlib, html, json

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'readable'
SOURCE=ROOT/'c2-output'


def _time(m: int) -> str:
    return f'{m//60:02}:{m%60:02}'


def make_payload(problem: dict, candidate: dict) -> dict:
    # C2 simulation uses synthetic people and rooms only.
    if candidate['status'] != 'FEASIBLE':
        raise ValueError('Not a generated feasible candidate')
    from veni_grid_contract.core_v1 import CoreProblem,CoreWitness
    from veni_grid_contract.conformance import review_core
    parsed_p=CoreProblem.model_validate(problem);parsed_w=CoreWitness.model_validate(candidate)
    validated=review_core(parsed_p,parsed_w)
    if validated.result!='CANDIDATE_HARD_VALIDATED':
        raise ValueError(f'Independent hard validation failed: {validated.result}')
    activities={a['id']:a for a in problem['activities']}
    events={e['id']:e for e in problem['events']}
    windows={w['id']:w for w in problem['windows']}
    resources={r['id']:r for r in problem['resources']}
    family_sections=defaultdict(list)
    for e in problem['events']:
        name=activities[e['activity_id']]['label'].replace('Invented ','')
        if e['offering_id'] not in family_sections[name]:
            family_sections[name].append(e['offering_id'])
    class_alias={off:f'Class {name}{i+1}' for name,os in sorted(family_sections.items()) for i,off in enumerate(sorted(os))}
    sizes=Counter(oid for x in candidate['enrollment_assignments'] for oid in x['offering_ids'])
    records=[]
    for a in candidate['event_assignments']:
        e=events[a['event_id']]
        w=windows[a['start_window_id']]
        day=w['day_id']; start=w['start_minute'];
        n=e['duration']['count']
        if e['duration']['unit']!='WINDOWS': raise ValueError('Human timetable sample expects discrete windows')
        same_day=sorted([x for x in problem['windows'] if x['day_id']==day and x['bell_id']==w['bell_id']],key=lambda x:x['sequence'])
        index=next(i for i,x in enumerate(same_day) if x['id']==w['id'])
        occupied=same_day[index:index+n]
        if len(occupied)!=n:raise ValueError('Duration over day boundary unsupported in this first display')
        end=occupied[-1]['end_minute']
        if not all(x['sequence']==w['sequence']+i for i,x in enumerate(occupied)):raise ValueError('Non-consecutive double')
        ids={next(q['role'] for q in e['requirements'] if q['id']==r['requirement_id']):r['resource_ids'][0] for r in a['resource_allocations']}
        tid=ids['TEACHER'];room=ids['ROOM'];
        subject=activities[e['activity_id']]['label'].replace('Invented ','')
        if not (subject in {'A','B','C','D'}): raise ValueError('Only the known synthetic sample is accepted here')
        lab='LAB' in resources[room]['tags']
        records.append({'day':day,'period':w['sequence'],'end_period':occupied[-1]['sequence'],
            'start':start,'end':end,'time_label':_time(start)+'–'+_time(end),
            'subject':f'Subject {subject}','subject_key':subject,
            'class':class_alias[e['offering_id']],'pupils':sizes[e['offering_id']],
            'teacher':f'Teacher {tid[-1]}','teacher_key':tid[-1],
            'room':'Science laboratory' if lab else f'Classroom {room.split(":R")[-1]}',
            'room_key':room,'double':n>1,'lab':lab,'event_id':e['id']})
    records.sort(key=lambda x:(x['day'],x['start'],x['class']))
    return {'kind':'ACTUAL_VALIDATED_C2_CANDIDATE','problem_id':problem['problem_id'],
        'model_version':problem['model_version'],'synthetic_only':True,
        'school_context':'Demonstration, not a real institution',
        'candidate_sha256':hashlib.sha256(json.dumps(candidate,sort_keys=True).encode()).hexdigest(),
        'count':len(records),'lesson_records':records,'days':sorted({r['day'] for r in records}),
        'sections':len({r['class'] for r in records}),'teachers':sorted({r['teacher'] for r in records}),
        'rooms':sorted({r['room'] for r in records})}


def render_html(payload: dict) -> str:
    data=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Veni Grid | Teaching Timetable Explained</title>
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Arial,sans-serif;color:#193048;background:#f4f6f8;--ink:#193048;--muted:#677b8c;--line:#dce4ec;--teal:#0e8b83;--navy:#172d46}*{box-sizing:border-box}
body{margin:0}button,select{font:inherit}button{cursor:pointer}button:focus-visible,select:focus-visible{outline:3px solid #57b8b1;outline-offset:3px}
header{background:var(--navy);color:white;padding:22px max(24px,calc((100% - 1370px)/2));display:flex;justify-content:space-between;align-items:center;gap:20px}header small{font-weight:700;letter-spacing:.16em;color:#8fdfd4}header h1{font-size:clamp(23px,2.8vw,34px);margin:5px 0;font-weight:780;letter-spacing:-.04em}header p{color:#becdda;margin:0;font-size:13px}.header-badge{border:1px solid #54748a;color:#e3f8ef;border-radius:100px;padding:10px 15px;font-size:12px;white-space:nowrap}
main{max-width:1370px;margin:auto;padding:28px 24px 60px}.intro{display:grid;grid-template-columns:1.5fr 1fr;gap:18px;margin-bottom:18px}.panel{background:#fff;border:1px solid var(--line);border-radius:17px;box-shadow:0 3px 20px #223b5710}.hero{padding:24px}.eyebrow{font-size:11px;letter-spacing:.1em;text-transform:uppercase;font-weight:750;color:#158b82}.hero h2{margin:8px 0;font-size:21px;letter-spacing:-.025em}.hero p{line-height:1.65;margin:7px 0;color:#4b6075;font-size:14px}.caution{display:flex;gap:8px;align-items:flex-start;margin-top:15px;border-radius:10px;background:#f0f5fb;padding:12px;color:#4c6279;font-size:12px;line-height:1.5}.stats{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;padding:18px}.stat{background:#f7fafc;border-radius:11px;padding:13px}.stat b{display:block;font-size:27px;letter-spacing:-.04em}.stat span{font-size:12px;color:var(--muted)}
.controls{display:flex;gap:13px;flex-wrap:wrap;align-items:end;padding:16px;margin-bottom:18px}.control label{display:block;color:#6c7b8a;font-size:11px;font-weight:750;margin-bottom:5px}.control select{background:white;padding:9px 12px;border:1px solid #ced9e3;border-radius:9px;min-height:40px;min-width:180px;color:#1b344a}.pill-group{display:flex;border-radius:10px;background:#eaf0f4;padding:4px;gap:3px}.pill-group button{border:0;padding:9px 13px;color:#50667a;background:transparent;border-radius:8px;font-size:12px}.pill-group button.active{background:#fff;color:#0f746b;box-shadow:0 1px 6px #203d501c;font-weight:780}.spacer{flex:1}.button{border:1px solid #d1dce5;border-radius:9px;background:#fff;padding:10px 14px;color:#29445a;font-weight:720;font-size:12px}.button.teal{border-color:#117d79;background:#0f867e;color:white}
.section{margin-bottom:24px}.daytitle{display:flex;align-items:baseline;gap:10px;margin:0 0 15px}.daytitle h2{margin:0;font-size:21px;letter-spacing:-.03em}.daytitle p{margin:0;color:var(--muted);font-size:13px}.time-row{display:grid;grid-template-columns:160px minmax(0,1fr);border-radius:15px;background:#fff;border:1px solid var(--line);margin-bottom:12px;overflow:hidden}.time{padding:20px 15px;background:#f0f5f8;border-right:1px solid var(--line)}.time strong{display:block;font-size:17px;letter-spacing:-.03em}.time span{display:block;font-size:11px;margin-top:5px;color:#5d7488}.time .same{font-size:11px;color:#14847a;font-weight:750;margin-top:15px}.cards{padding:14px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px}.lesson{border-radius:13px;border:1px solid #e2e8ef;border-left:5px solid var(--lesson-accent);background:var(--lesson-bg);padding:16px 15px 14px;min-height:155px;display:flex;flex-direction:column;gap:7px}.lesson.muted{opacity:.18;filter:grayscale(1)}.lesson h3{font-size:16px;line-height:1.3;margin:0}.lesson .tag{font-size:10px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:var(--lesson-accent)}.lesson .class{font-size:12px;color:#51677a}.details{margin-top:auto;display:grid;gap:6px}.detail{display:flex;align-items:center;gap:7px;font-size:12px;color:#254052}.ico{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:7px;background:#ffffffbf;font-size:13px}.lesson .duration{font-size:11px;color:#567287}.lesson .duration strong{color:#244c63}.no-results{grid-column:1/-1;text-align:center;color:#6c8293;font-size:13px;padding:25px}.legend{display:flex;gap:13px;flex-wrap:wrap;margin-top:18px;padding:18px 20px;align-items:center}.legend strong{font-size:13px;margin-right:5px}.key{font-size:12px;display:flex;gap:7px;align-items:center;color:#526a7b}.key i{display:block;width:11px;height:11px;border-radius:3px;background:var(--c)}.foot{margin-top:18px;font-size:12px;color:#677f8d;line-height:1.6}.foot b{color:#34546b}
@media(max-width:950px){.intro{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:620px){header{padding:20px;flex-wrap:wrap}.header-badge{white-space:normal}main{padding:16px}.stats{grid-template-columns:repeat(2,1fr)}.time-row{display:block}.time{border-right:0;border-bottom:1px solid var(--line);padding:12px 15px}.time strong,.time span{display:inline;margin-right:10px}.time .same{display:inline}.cards{grid-template-columns:1fr}.lesson{min-height:120px}.controls{align-items:stretch}.control{flex:1;min-width:145px}.control select{min-width:0;width:100%}}
@media print{body{background:white}header{background:#172d46!important;print-color-adjust:exact;-webkit-print-color-adjust:exact}.controls{display:none}.intro{display:block}.stats{display:flex;gap:12px}.stat{flex:1}.cards{grid-template-columns:repeat(3,1fr)}.lesson{break-inside:avoid;min-height:130px;-webkit-print-color-adjust:exact;print-color-adjust:exact}.section{break-inside:avoid}.time-row{break-inside:avoid}main{padding:14px}.foot{font-size:10px}}
</style></head>
<body><header><div><small>VENI GRID / TEACHING TIMETABLE</small><h1>Where does each class go?</h1><p>An easy-to-read view of the actual generated teaching schedule</p></div><div class="header-badge">✓ Independently checked · Synthetic example</div></header>
<main>
<div class="intro"><section class="panel hero"><span class="eyebrow">Start here</span><h2>How to read this timetable</h2><p>Each <b>time band</b> shows lessons that happen <b>at the same time</b>. Each coloured card is one separate class, with its teacher, classroom and number of pupils. Switch between the two days or filter by teacher, room or class.</p><p>The laboratory lessons take <b>two consecutive periods</b>. Other subject lessons take one period, even when a longer shared time band is shown.</p><div class="caution">ⓘ This is a two-day demonstration using <b>invented pupils, teachers, subjects and rooms</b>. “Subject A/B/C/D” are placeholders. It is not a real school timetable or a complete ten-day curriculum.</div></section><section class="panel stats" aria-label="Timetable summary"><div class="stat"><b id="stat-lessons">18</b><span>Scheduled lessons</span></div><div class="stat"><b id="stat-groups">9</b><span>Separate class groups</span></div><div class="stat"><b id="stat-teachers">4</b><span>Qualified teachers</span></div><div class="stat"><b id="stat-rooms">3</b><span>Suitable teaching rooms</span></div></section></div>
<div class="panel controls"><div class="control"><label>Show day</label><div class="pill-group" id="day-choice" role="group" aria-label="Choose timetable day"><button data-day="day:D1" class="active" aria-pressed="true">Day 1</button><button data-day="day:D2" aria-pressed="false">Day 2</button><button data-day="ALL" aria-pressed="false">Both days</button></div></div><div class="control"><label for="teacher-filter">Teacher</label><select id="teacher-filter"><option value="ALL">All teachers</option></select></div><div class="control"><label for="room-filter">Classroom</label><select id="room-filter"><option value="ALL">All classrooms</option></select></div><div class="control"><label for="class-filter">Class group</label><select id="class-filter"><option value="ALL">All classes</option></select></div><div class="spacer"></div><button class="button" id="reset">Reset filters</button><button class="button teal" id="print">Print / Save as PDF</button></div>
<div id="timetable" aria-live="polite"></div>
<div class="panel legend" id="legend"><strong>Colour guide</strong><span class="key"><i style="--c:#396bc5"></i>Subject A</span><span class="key"><i style="--c:#8b65c6"></i>Subject B</span><span class="key"><i style="--c:#cb853e"></i>Subject C</span><span class="key"><i style="--c:#159484"></i>Subject D · laboratory</span></div>
<p class="foot"><b>Verification:</b> This layout is produced from the actual C2 CP-SAT event assignments and original teaching-room/teacher selections. Every occurrence passed the independent hard checker. <b>Scope:</b> synthetic O1/C2 example only; other timetables were not loaded, changed or published.</p></main>
<script type="application/json" id="result-data">'''+data+'''</script>
<script>
'use strict';
const model=JSON.parse(document.getElementById('result-data').textContent);
const byId=(id)=>document.getElementById(id);
let dayChoice='day:D1';
const palettes={A:{bg:'#edf3ff',accent:'#396bc5'},B:{bg:'#f3effd',accent:'#8b65c6'},C:{bg:'#fff5e9',accent:'#cb853e'},D:{bg:'#e8f8f3',accent:'#159484'}};
function addOption(id,text){const opt=document.createElement('option');opt.value=id;opt.textContent=text;return opt}
function fill(){for(const t of model.teachers)byId('teacher-filter').appendChild(addOption(t,t));for(const r of model.rooms)byId('room-filter').appendChild(addOption(r,r));for(const c of [...new Set(model.lesson_records.map(r=>r.class))].sort())byId('class-filter').appendChild(addOption(c,c));byId('stat-lessons').textContent=model.count;byId('stat-groups').textContent=model.sections;byId('stat-teachers').textContent=model.teachers.length;byId('stat-rooms').textContent=model.rooms.length}
function node(tag,cl,text){const el=document.createElement(tag);if(cl)el.className=cl;if(text!==undefined)el.textContent=text;return el}
function isMatch(r){return ['teacher-filter','room-filter','class-filter'].every((id)=>{const v=byId(id).value;return v==='ALL'||r[id.slice(0,id.indexOf('-'))]===v})}
function tile(r){const colors=palettes[r.subject_key];const el=node('article','lesson');el.style.setProperty('--lesson-bg',colors.bg);el.style.setProperty('--lesson-accent',colors.accent);
const title=node('h3',null,r.subject);const tag=node('div','tag',r.lab?'LABORATORY LESSON':'CLASS LESSON');const group=node('div','class',r.class+' · '+r.pupils+' pupils');const det=node('div','details');
for(const [symbol,label] of [['👩‍🏫',r.teacher],['🏫',r.room]]){const row=node('div','detail');row.append(node('span','ico',symbol),node('span',null,label));det.appendChild(row)}
const duration=node('div','duration',r.time_label+' · '+(r.double?'Double lesson (2 periods)':'Single lesson (1 period)'));el.append(tag,title,group,det,duration);return el}
function render(){const target=byId('timetable');target.replaceChildren();let visible=0;const records=model.lesson_records;
for(const day of model.days){if(dayChoice!=='ALL'&&day!==dayChoice)continue;
const section=node('section','section');const heading=node('div','daytitle');heading.append(node('h2',null,day==='day:D1'?'Day 1':'Day 2'),node('p',null,'Synthetic teaching cycle'));section.appendChild(heading);
const starts=[...new Set(records.filter(r=>r.day===day).map(r=>r.start))].sort((a,b)=>a-b);
for(const start of starts){const rows=records.filter(r=>r.day===day&&r.start===start);const matching=rows.filter(isMatch);if(!matching.length)continue;visible+=matching.length;
const slot=node('div','time-row');const clock=node('div','time');const end=Math.max(...rows.map(r=>r.end));const hm=(x)=>String(Math.floor(x/60)).padStart(2,'0')+':'+String(x%60).padStart(2,'0');clock.append(node('strong',null,hm(start)+'–'+hm(end)),node('span',null,'Periods '+rows[0].period+'–'+Math.max(...rows.map(r=>r.end_period))),node('span','same',rows.length+' classes concurrently'));
const cards=node('div','cards');for(const r of matching)cards.appendChild(tile(r));slot.append(clock,cards);section.appendChild(slot)}
if(section.querySelector('.time-row'))target.appendChild(section)}
if(!visible){const msg=node('div','panel no-results','No class matches these filters. Try Reset filters.');target.appendChild(msg)}
}
function dayChange(value){dayChoice=value;document.querySelectorAll('[data-day]').forEach(b=>{const active=b.dataset.day===value;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active))});render()}
byId('day-choice').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>dayChange(b.dataset.day)));
for(const id of ['teacher-filter','room-filter','class-filter'])byId(id).addEventListener('change',render);
byId('reset').addEventListener('click',()=>{for(const id of ['teacher-filter','room-filter','class-filter'])byId(id).value='ALL';dayChange('day:D1')});
byId('print').addEventListener('click',()=>{dayChange('ALL');window.print()});
fill();render();
</script></body></html>'''


def run(source=SOURCE,out=OUT):
    out.mkdir(parents=True,exist_ok=True)
    problem=json.loads((source/'c2-placement-problem.json').read_text())
    candidate=json.loads((source/'c2-generated-teaching-timetable.json').read_text())
    payload=make_payload(problem,candidate)
    if payload['count']!=18 or payload['sections']!=9:
        raise ValueError('Unexpected sample fixture; review new sample before claiming layout parity')
    (out/'c2-teaching-timetable-explained.html').write_text(render_html(payload),encoding='utf-8')
    (out/'c2-teaching-display-source.json').write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
    return payload

if __name__=='__main__':
    v=run()
    print(f"Human display built from C2 actual candidate: {v['count']} lessons, {v['sections']} groups, {len(v['teachers'])} teachers, {len(v['rooms'])} rooms")
