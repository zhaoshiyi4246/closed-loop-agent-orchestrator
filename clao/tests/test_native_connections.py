"""Current service contracts through the existing production transport, offline."""
import json
import pytest

from loopcore import ao_legacy
from loopcore.model_profiles import native_profile, validate_profiles, SERVICE, KIMI_SERVICE
from tests.test_p01_bigmodel import glm_http, configuration, envelope, roles
from tests.test_codex_verifier import _input, _result


def test_glm53_actual_transport_parameters_and_verifier_verdict(glm_http):
    glm_http.replies = [(200, envelope(_result()))]
    cfg = configuration(roles=('verifier',), model='glm-5.3', thinking='enabled', reasoning_effort='low')
    _, _, verifier = roles(cfg)
    assert verifier.verify(_input(), 'VERIFY-CODEX').verdict == 'PASS'
    assert len(glm_http.calls) == 1
    call = glm_http.calls[0]
    assert call['model'] == 'glm-5.3'
    assert call['thinking'] == {'type': 'enabled'} and call['reasoning_effort'] == 'low'
    assert call['response_format'] == {'type': 'json_object'} and 'tools' not in call


def test_new_connection_catalog_and_frozen_glm53_contract_without_key(monkeypatch):
    from loopcore import credentials
    monkeypatch.setattr(credentials, 'credentials', lambda *args: pytest.fail('Creation does not read a key or call a service'))
    catalog = ao_legacy.evaluate({'action': 'catalog'})['catalog']
    assert catalog['services'][0]['models'][0]['id'] == 'glm-5.3'
    for service, model in ((SERVICE, 'glm-5.3'), (SERVICE, 'glm-4.7'), (KIMI_SERVICE, 'kimi-k3')):
        request = dict(action='connection', id='native-' + 'a' * 32, name='测试连接', service=service, model=model)
        result = ao_legacy.evaluate(request)
        assert result == ao_legacy.evaluate(request)
        row = result['rows'][0]['document']
        assert row['model'] == model and row['billing'] == 'standard_api' and row['compatible']
        assert row['profile']['max_attempts'] == 1
        assert 'apiKey' not in json.dumps(result)


def test_custom_model_identity_uses_same_transport_without_claiming_admission():
    p = native_profile('custom', SERVICE, 'glm-future-text')
    validate_profiles([p])
    assert p['model'] == 'glm-future-text' and p['endpoint'].startswith('https://open.bigmodel.cn/')
    for change in ({'model': '../invalid name'}, {'model': 'glm-5.3', 'thinking': 'disabled'},
                   {'reasoning_effort': 'medium'}, {'endpoint': 'https://proxy.invalid/v1'}):
        with pytest.raises(ValueError):
            validate_profiles([dict(p, **change)])
