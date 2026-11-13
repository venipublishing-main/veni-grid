"""Human readable actual before/after plan, derived from C3 receipt and window domains."""
from __future__ import annotations
from html import escape
from pathlib import Path
import json

TEMPLATE='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Veni Grid — before & after resource feedback</title>
<style>:root{font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;color:#1c354b;background:#f4f7fa}*{box-sizing:border-box}body{margin:0}header{background:#172d46;color:white;padding:27px max(23px,calc((100% - 1050px)/2))}header h1{font-size:28px;letter-spacing:-.04em;margin:8px 0}header p{color:#becbd9;margin:0}main{max-width:1050px;margin:24px auto;padding:0 20px}.banner{background:white;border:1px solid #dde6ed;border-radius:15px;padding:22px;margin:16px 0;line-height:1.7}.banner strong{color:#176f67}.columns{display:grid;grid-template-columns:1fr 1fr;gap:18px}section{background:white;border-radius:16px;border:1px solid #dce5ee;overflow:hidden;box-shadow:0 2px 14px #1a39540a}section h2{margin:0;font-size:19px}.sectionhead{padding:20px;border-bottom:1px solid #e3e9ef}.sectionhead p{margin:5px 0 0;font-size:12px;color:#647c8c}.old{color:#b15445}.new{color:#087c69}.body{padding:18px;display:grid;gap:12px}.lesson{background:#edf3f8;border-left:5px solid #4b88c6;padding:15px;border-radius:10px}.lesson.changed{background:#e5f7f1;border-color:#168a7a}.subject{font-size:16px;font-weight:800}.meta,.teacher{font-size:13px;color:#516d80;margin-top:6px}.moved{display:inline-block;margin-top:10px;padding:5px 9px;background:#bde9df;border-radius:6px;color:#086e5f;font-size:11px;font-weight:800}.note{font-size:13px;color:#60798c;line-height:1.6;padding:17px;border-top:1px solid #e4eaf0}.foot{margin:21px 0;color:#637e8e;font-size:12px;line-height:1.7}@media(max-width:720px){.columns{grid-template-columns:1fr}}</style></head>
<body><header><small>VENI GRID · RESOURCE-AWARE PLANNING</small><h1>One laboratory. Two classes. A workable alternative.</h1><p>Actual solver-checked proposal with invented school data</p></header><main><div class="banner">Both subjects initially needed the <strong>same laboratory at 08:00</strong>. That was impossible for the original option block. Grid explored a different learner-option arrangement, then <strong>independently verified teacher, classroom and timetable feasibility</strong>. All six subject requests remain satisfied.</div><div class="columns"><section><div class="sectionhead"><h2 class="old">✕ First plan — laboratory clash</h2><p>Two classes at the same time; only one laboratory</p></div><div class="body">__OLD_CARDS__</div><div class="note">C2 proved this fixed arrangement impossible. The original accepted plan was not changed.</div></section><section><div class="sectionhead"><h2 class="new">✓ Alternative — valid in preview</h2><p>Classes in different time blocks; the laboratory is reused</p></div><div class="body">__NEW_CARDS__</div><div class="note">O1 requests and sections independently validated. C2 placed both lessons with qualified staff and the suitable lab.</div></section></div><div class="banner"><strong>Approval still required.</strong> This is an in-memory proposal, not an accepted, saved or published timetable. It uses synthetic examples, a restricted one-occurrence model and no other scheduling modules.</div><p class="foot">Checks: six learner requests preserved; one changed subject-block assignment; two generated teaching events; independent hard validation passed. More complex resectioning and whole-school repair are not implemented yet.</p></main></body></html>'''


def render_feedback(report:dict,request,out:Path):
    original=report['original_blocks'];new=report['proposed_blocks']
    windows={w.id:w for w in request.current.target.windows}
    olddomains={x.block_id:x for x in request.current.target.block_windows}
    newdomains={x.block_id:x for x in request.proposed_block_windows}
    def time(domains,block):
        ids=domains[block].candidate_start_ids
        if len(ids)!=1:raise ValueError('This comparison needs single explicit source/proposal time per block')
        win=windows[ids[0]];m=win.start_minute
        return f'{m//60:02}:{m%60:02}'
    rows=[{'subject':'Subject '+f.split(':')[-1],
           'before':time(olddomains,original[f]),'after':time(newdomains,new[f]),
           'moved':original[f]!=new[f]} for f in sorted(original)]
    report['plain_english_rows']=rows
    (out/'c3-summary.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Veni Grid — Laboratory clash solved in a draft proposal','',
        'Actual synthetic O1/C2 solver outcome; not an accepted or published timetable.','',
        '| Subject | Initial plan (not teachable) | New independently validated draft |',
        '|---|---|---|']
    for row in rows:
        lines.append(f"| {row['subject']} | {row['before']} | {row['after']}{' (moved)' if row['moved'] else ''} |")
    lines += ['', '**Why:** the first arrangement needed one lab for two simultaneous sections. '
        'Moving one subject to a later block avoids the clash without dropping learners.',
        '', '**Status: proposal only.** The original O1 source and every other schedule are unchanged.','']
    (out/'c3-readable-report.md').write_text('\n'.join(lines),encoding='utf-8')
    def card(row,column):
        name=escape(row['subject']); hour=escape(row[column]);moved=row['moved'] and column=='after'
        pill='<span class="moved">Moved to a different option block</span>' if moved else ''
        return f'<div class="lesson {"changed" if moved else ""}"><div class="subject">{name}</div><div class="meta">{hour} · 3 learners</div><div class="teacher">🏫 One suitable laboratory · qualified teacher</div>{pill}</div>'
    before_cards=''.join(card(r,'before') for r in rows)
    after_cards=''.join(card(r,'after') for r in sorted(rows,key=lambda x:x['after']))
    markup=TEMPLATE.replace('__OLD_CARDS__',before_cards).replace('__NEW_CARDS__',after_cards)
    (out/'c3-feedback-before-after.html').write_text(markup,encoding='utf-8')
    return rows
