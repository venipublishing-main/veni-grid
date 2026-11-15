"""C6 signed-token negative tests. All keys and identities are synthetic."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import jwt
from jwt.algorithms import RSAAlgorithm, ECAlgorithm
from cryptography.hazmat.primitives.asymmetric import rsa,ec
import pytest

from veni_grid_authority.identity_gate import (IdentityConfig,IdentityGate,
    IdentityRejected,VerifiedVeniIdentity,bind_grid_principal)

ISS="https://example-veni-staging.supabase.co/auth/v1"
AUD="authenticated"

@pytest.fixture(scope="module")
def keys():
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    jwk=json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update({"kid":"veni-key-1","alg":"RS256","use":"sig"})
    return private,jwk

@pytest.fixture
def source(keys):
    key,jwk=keys
    jwk=dict(jwk)
    subject=str(uuid4());session=str(uuid4())
    now=int(datetime.now(timezone.utc).timestamp())
    payload={"iss":ISS,"aud":AUD,"sub":subject,"session_id":session,
             "iat":now,"nbf":now-2,"exp":now+1200,"role":"authenticated",
             "aal":"aal2","is_anonymous":False,
             "user_metadata":{"organisation_id":"org:forged","is_admin":True}}
    jwks={"keys":[jwk]}
    active={session}
    gate=IdentityGate(config=IdentityConfig(issuer=ISS),trusted_jwks=lambda:jwks,
                      active_session=lambda user,sid:user==subject and sid in active)
    def token(changes=None, headers=None, signer=None, alg="RS256"):
        claims={**payload,**(changes or {})}
        return jwt.encode(claims,signer or key,algorithm=alg,headers={"kid":"veni-key-1",**(headers or {})})
    return {"payload":payload,"token":token,"gate":gate,"active":active,"jwk":jwk,"jwks":jwks,"private":key}

def denied(gate,token,code,action="view"):
    with pytest.raises(IdentityRejected) as e:
        gate.verify(token,action=action)
    assert e.value.code==code,e.value.code


def test_valid_rsa_signed_token_and_strict_issuer_audience(source):
    v=source['gate'].verify(source['token']())
    assert v.subject_id==source['payload']['sub'] and v.session_id==source['payload']['session_id']
    assert v.assurance=='aal2' and not hasattr(v,'organisation_id')


def test_valid_mfa_approved_action_requires_aal2(source):
    assert source['gate'].verify(source['token'](),action='approve').assurance=='aal2'
    assert source['gate'].verify(source['token']({'aal':'aal1'}),action='propose').assurance=='aal1'
    for action in ('approve','publish','restore','grant'):
        denied(source['gate'],source['token']({'aal':'aal1'}),'MFA_STEP_UP_REQUIRED',action)


def test_session_revocation_denies_valid_signed_token(source):
    access=source['token']()
    source['active'].clear()
    denied(source['gate'],access,'SESSION_NOT_ACTIVE')


def test_session_oracle_unavailable_fails_closed(source):
    gate=IdentityGate(config=IdentityConfig(issuer=ISS),trusted_jwks=lambda:source['jwks'],
                      active_session=lambda *args:1/0)
    denied(gate,source['token'](),'SESSION_STATUS_UNAVAILABLE')


def test_unsigned_symmetric_or_unknown_header_never_accepted(source):
    payload=source['payload']; s=jwt.encode(payload,'attacker-secret-which-is-long-enough-for-hs256',algorithm='HS256',headers={'kid':'veni-key-1'})
    denied(source['gate'],s,'UNTRUSTED_KEY_OR_ALGORITHM')
    denied(source['gate'],source['token'](headers={'kid':'absent'}),'UNKNOWN_OR_DUPLICATE_SIGNING_KEY')


def test_token_supplied_jwks_url_and_critical_header_are_not_followed(source):
    for header in ({'jku':'https://evil.test/jwks.json'},{'x5u':'https://evil.test/x509'},
                   {'crit':['new']},{'jwk':source['jwk']}):
        with pytest.raises(IdentityRejected) as e: source['gate'].verify(source['token'](headers=header))
        assert e.value.code in ('UNTRUSTED_TOKEN_HEADER','INVALID_TOKEN_HEADER')


def test_duplicate_signing_key_fails_closed(source):
    source['jwks']['keys'].append(dict(source['jwk']))
    denied(source['gate'],source['token'](),'UNKNOWN_OR_DUPLICATE_SIGNING_KEY')


def test_wrong_issuer_audience_and_invalid_signature(source):
    for changed in ({'iss':'https://another.supabase.co/auth/v1'},{'aud':'different'}):
        denied(source['gate'],source['token'](changed),'SIGNATURE_OR_CLAIMS_INVALID')
    attacker=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    denied(source['gate'],source['token'](signer=attacker),'SIGNATURE_OR_CLAIMS_INVALID')


def test_expired_future_and_missing_claims_fail(source):
    now=source['payload']['iat']
    for p in ({'exp':now-30},{'nbf':now+720},{'iat':now+720},
              {'exp':now+999999},{'role':'service_role'},{'is_anonymous':True},
              {'sub':'not-a-uuid'},{'session_id':'not-a-uuid'}):
        e=IdentityRejected
        with pytest.raises(e):source['gate'].verify(source['token'](p))
    p=dict(source['payload']);p.pop('session_id')
    short=jwt.encode(p,source['private'],algorithm='RS256',headers={'kid':'veni-key-1'})
    denied(source['gate'],short,'SIGNATURE_OR_CLAIMS_INVALID')



def test_long_lived_signed_token_is_rejected(source):
    now=source['payload']['iat']
    denied(source['gate'],source['token']({'exp':now+8000}),'ACCOUNT_CLAIMS_INVALID')


def test_account_metadata_cannot_grant_school_membership(source):
    verified=source['gate'].verify(source['token']())
    with pytest.raises(IdentityRejected) as e:
        bind_grid_principal(verified,organisation_id='org:forged',active_membership=lambda u,o:False)
    assert e.value.code=='GRID_MEMBERSHIP_REQUIRED'
    good=bind_grid_principal(verified,organisation_id='org:synthetic',
                            active_membership=lambda u,o:u==verified.subject_id and o=='org:synthetic')
    assert good.organisation_id=='org:synthetic' and good.subject_id==verified.subject_id


def test_user_submitted_organisation_object_is_not_verified_identity(source):
    with pytest.raises(IdentityRejected) as e:
        bind_grid_principal({'sub':source['payload']['sub'],'org_id':'org:synthetic'},
                            organisation_id='org:synthetic',active_membership=lambda *a:True)
    assert e.value.code=='VERIFIED_IDENTITY_REQUIRED'


def test_missing_membership_registry_fails_closed(source):
    ident=source['gate'].verify(source['token']())
    with pytest.raises(IdentityRejected) as e:
        bind_grid_principal(ident,organisation_id='org:synthetic',active_membership=lambda *x:1/0)
    assert e.value.code=='MEMBERSHIP_STATUS_UNAVAILABLE'


def test_malformed_signature_key_metadata(source):
    source['jwks']['keys'][0]['kty']='oct'
    denied(source['gate'],source['token'](),'KEY_TYPE_MISMATCH')


def test_bad_verification_config_and_prohibited_actions(source):
    with pytest.raises(ValueError):IdentityConfig(issuer='http://bad.test/auth/v1')
    with pytest.raises(ValueError):IdentityConfig(issuer=ISS,algorithms=('HS256',))
    denied(source['gate'],source['token'](),'UNKNOWN_ACTION',action='takeover')


def test_production_key_selection_never_loads_jwks_from_token(source):
    requests=[]
    gate=IdentityGate(config=IdentityConfig(issuer=ISS),trusted_jwks=lambda:requests.append('fixed') or source['jwks'],
                      active_session=lambda *a:True)
    gate.verify(source['token']())
    assert requests==['fixed']


def test_ecdsa_tokens_supported_with_key_type_lock(source):
    ec_private=ec.generate_private_key(ec.SECP256R1())
    jwk=json.loads(ECAlgorithm.to_jwk(ec_private.public_key()));jwk.update({'kid':'ec-valid','alg':'ES256','use':'sig'})
    pub={"keys":[jwk]}
    gate=IdentityGate(config=IdentityConfig(issuer=ISS),trusted_jwks=lambda:pub,active_session=lambda *a:True)
    t=jwt.encode(source['payload'],ec_private,algorithm='ES256',headers={'kid':'ec-valid'})
    assert gate.verify(t).session_id==source['payload']['session_id']
