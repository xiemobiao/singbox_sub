import base64
import json
from fastapi.testclient import TestClient

import main
from singbox_generator import generate_singbox_url


client = TestClient(main.app)


def _decode_b64_config(encoded: str) -> dict:
    pad = (-len(encoded)) % 4
    raw = base64.urlsafe_b64decode(encoded + ('=' * pad) if pad else encoded)
    return json.loads(raw)


def test_generator_uses_tls_certificate_from_pem_and_base64():
    pem_text = """-----BEGIN CERTIFICATE-----\nMIIB...FAKE...CERT\n-----END CERTIFICATE-----\n"""
    nodes_pem = [{
        'server': 'example.com',
        'port': 443,
        'password': 'pw',
        'sni': 'example.com',
        'insecure': False,
        'obfs': None,
        'obfs_password': None,
        'alpn': ['h3'],
        'ca': pem_text,
    }]
    enc_pem = generate_singbox_url(nodes_pem)
    cfg_pem = _decode_b64_config(enc_pem)
    cert_lines = cfg_pem['outbounds'][0]['tls'].get('certificate')
    assert isinstance(cert_lines, list)
    assert cert_lines[0].startswith('-----BEGIN CERTIFICATE-----')

    b64_pem = base64.b64encode(pem_text.encode()).decode()
    nodes_b64 = [{
        **nodes_pem[0],
        'ca': b64_pem,
    }]
    enc_b64 = generate_singbox_url(nodes_b64)
    cfg_b64 = _decode_b64_config(enc_b64)
    cert_lines2 = cfg_b64['outbounds'][0]['tls'].get('certificate')
    assert isinstance(cert_lines2, list)
    assert cert_lines2[0].startswith('-----BEGIN CERTIFICATE-----')


def test_subscription_format_json_and_short_link():
    # 构造一个最小可解析的 hy2 链接
    sub = 'hysteria2://example.com:443?password=pw&sni=example.com&insecure=0'
    resp = client.post('/convert', json={'subscription': sub})
    assert resp.status_code == 200
    data = resp.json()
    # JSON 直读
    b64 = data['singbox_config']
    resp_json = client.get(f'/subscription/{b64}?format=json')
    assert resp_json.status_code == 200
    j = resp_json.json()
    assert 'outbounds' in j and isinstance(j['outbounds'], list)
    assert 'route' in j and j['route'].get('final') == 'proxy'

    # 短链访问（JSON）
    short_url = data['subscription_url_short_json']
    # TestClient 支持完整 URL
    resp_short = client.get(short_url)
    assert resp_short.status_code == 200
    j2 = resp_short.json()
    assert 'outbounds' in j2 and isinstance(j2['outbounds'], list)
    assert 'route' in j2 and j2['route'].get('final') == 'proxy'


def test_adblock_and_custom_rules(monkeypatch):
    monkeypatch.setenv('ENABLE_ADBLOCK', 'true')
    monkeypatch.setenv('BYPASS_DOMAINS', 'example.cn, *.local')
    monkeypatch.setenv('PROXY_DOMAINS', 'example.com')
    monkeypatch.setenv('ENABLE_DOH_DIRECT', '1')

    nodes = [{
        'server': 'example.com',
        'port': 443,
        'password': 'pw',
        'sni': 'example.com',
        'insecure': False,
        'obfs': None,
        'obfs_password': None,
        'alpn': None,
        'ca': None,
    }]
    enc = generate_singbox_url(nodes)
    cfg = _decode_b64_config(enc)
    # 存在 block 出站
    assert any(ob.get('type') == 'block' and ob.get('tag') == 'block' for ob in cfg['outbounds'])
    # 存在自定义直连/代理域名规则
    domains = []
    for r in cfg['route']['rules']:
        if 'domain' in r:
            domains.extend(r['domain'])
    assert 'example.com' in domains and 'example.cn' in ','.join(domains)
