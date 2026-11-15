"""C6 real signature verification proof with generated, never persisted test keys.

Only synthetic claims; this is NOT a real Veni Account login or live DB test.
"""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
import jwt,json,html

from veni_grid_authority.identity_gate import (IdentityConfig,IdentityGate,
    IdentityRejected,bind_grid_principal)

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'c6-output'

def run():
    OUT.mkdir(exist_ok=True)
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    pub=json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    pub.update({'kid':'synthetic-venikey','alg':'RS256','use':'sig'})
    org='org:synthetic-school';subject=str(uuid4());session=str(uuid4())
    now=int(datetime.now(timezone.utc).timestamp())
    issuer='https://invented-veni-test.supabase.co/auth/v1'
    payload={'iss':issuer,'aud':'authenticated','sub':subject,
             'session_id':session,'role':'authenticated','aal':'aal2',
             'iat':now,'nbf':now-2,'exp':now+1200}
    live={session}
    gate=IdentityGate(config=IdentityConfig(issuer=issuer),
        trusted_jwks=lambda:{'keys':[pub]},
        active_session=lambda sub,sid:sub==subject and sid in live)
    token=jwt.encode(payload,private,algorithm='RS256',headers={'kid':'synthetic-venikey'})
    verified=gate.verify(token,action='approve')
    principal=bind_grid_principal(verified,organisation_id=org,
        active_membership=lambda sub,ten:sub==subject and ten==org)
    if principal.organisation_id!=org:raise RuntimeError('Tenant identity did not bind')
    refused=[]
    for label,claim,step in [('no_mfa',{**payload,'aal':'aal1'},'approve'),
                              ('wrong_issuer',{**payload,'iss':'https://evil.test/auth/v1'},'view')]:
        bad=jwt.encode(claim,private,algorithm='RS256',headers={'kid':'synthetic-venikey'})
        try:gate.verify(bad,action=step)
        except IdentityRejected as exc:refused.append({'case':label,'reason':exc.code})
        else:raise RuntimeError(f'Unexpected acceptance: {label}')
    live.clear()
    try:gate.verify(token,action='view')
    except IdentityRejected as exc:refused.append({'case':'revoked_session','reason':exc.code})
    else:raise RuntimeError('Revoked token accepted')
    report={'kind':'C6_OFFLINE_IDENTITY_SECURITY_PROBE','source':'SYNTHETIC_EPHEMERAL_RSA_KEYS',
       'identity':'CRYPTOGRAPHIC_SIGNATURE_AND_SESSION_GATE_VERIFIED',
       'tenant_permission':'SEPARATE_SERVER_MEMBERSHIP_REQUIRED',
       'rejections':refused,'jwt_issuer':'SYNTHETIC_ONLY',
       'live_veni_auth':'NOT_CONNECTED', 'live_sessions':'NOT_CONNECTED',
       'postgresql_migration':'UNAPPLIED_REVIEW_ONLY',
       'rls_execution':'NOT_RUN', 'publication':'NOT_GRANTED',
       'real_personal_data':'NONE'}
    (OUT/'c6-security-summary.json').write_text(json.dumps(report,indent=2)+'\n')
    rows=''.join(f'<tr><td>{html.escape(x["case"].replace("_"," ").title())}</td><td>Blocked</td><td><code>{html.escape(x["reason"])}</code></td></tr>' for x in refused)
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Veni Grid C6 — Identity & School Permission Gates</title>
<style>body{margin:0;background:#f3f6fa;color:#183049;font-family:Inter,system-ui,Arial}header{background:#172d46;color:white;padding:35px max(24px,calc((100% - 1000px)/2))}h1{margin:5px 0;font-size:clamp(25px,3vw,39px)}header p{color:#bfcfdd;max-width:700px}main{max-width:1000px;margin:auto;padding:22px}section{background:#fff;border:1px solid #dce6ef;border-radius:16px;padding:22px;margin-bottom:16px}section h2{font-size:20px;margin:0 0 15px}.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.step{background:#f0f5f9;padding:16px;border-radius:12px;border-top:4px solid #147f78}.step h3{font-size:14px;margin:8px 0}.step p{font-size:12px;color:#526d7e;line-height:1.6}.label{font-size:11px;font-weight:bold;letter-spacing:.1em;color:#16877e}.warn{padding:13px 17px;border-left:4px solid #b17c45;background:#fff6e8;border-radius:8px;line-height:1.6}table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid #e9edf2;text-align:left;padding:10px;font-size:13px}footer{font-size:12px;color:#637a8e;margin:20px 4px;line-height:1.6}@media(max-width:720px){.steps{grid-template-columns:1fr 1fr}}@media(max-width:460px){.steps{grid-template-columns:1fr}}</style>
<header><small>VENI GRID / C6 SECURITY GATE</small><h1>One Veni login. Separate school permissions.</h1><p>The connection we are building between the shared Veni Account and Veni Flow's independent school timetable authority.</p></header>
<main><section><h2>How a future approval should work</h2><div class="steps"><div class="step"><span class="label">1 · IDENTITY</span><h3>Sign in to Veni</h3><p>Server verifies Supabase signature, issuer, audience and active session.</p></div><div class="step"><span class="label">2 · SCHOOL</span><h3>Check membership</h3><p>Grid checks the chosen school separately. Veni membership alone grants nothing.</p></div><div class="step"><span class="label">3 · TIMETABLE</span><h3>Check exact rights</h3><p>Approval needs a schedule-scoped grant and MFA step-up.</p></div><div class="step"><span class="label">4 · RECORD</span><h3>Version safely</h3><p>Future PostgreSQL transaction checks current revision and appends audit. Not live yet.</p></div></div></section>
<section><h2>Actual offline security tests</h2><p>Fresh ephemeral RSA keys were used to sign and verify a synthetic JWT. This is real cryptography, not a mock signature or a real user login.</p><table><thead><tr><th>Attempt</th><th>Result</th><th>Reason</th></tr></thead><tbody>__ROWS__</tbody></table></section>
<section><div class="warn"><b>Not a live authorisation service.</b> The Veni staging Supabase project is inactive. The Grid private-schema SQL remains an unapplied draft. Browser access, real authentication, school permissions, approval, publishing and rollback are still disabled until the live PostgreSQL/RLS and session checks have been independently demonstrated.</div></section><footer>Source: synthetic C6 identity gate test receipt. No personal data, access tokens, signing keys or secrets have been saved in this page.</footer></main></html>'''.replace('__ROWS__',rows)
    (OUT/'c6-security-explained.html').write_text(page,encoding='utf-8')
    print(json.dumps(report,indent=2))
    return report
if __name__=='__main__':run()
