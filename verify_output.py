import base64
import json

# 从API响应中获取的base64字符串
encoded = "eyJvdXRib3VuZHMiOlt7InR5cGUiOiJoeXN0ZXJpYTIiLCJ0YWciOiJoeXN0ZXJpYS0wIiwic2VydmVyIjoiZXhhbXBsZS5jb20iLCJzZXJ2ZXJfcG9ydCI6NDQzLCJwYXNzd29yZCI6InRlc3QiLCJ1cF9tYnBzIjoxMDAsImRvd25fbWJwcyI6MTAwLCJ0bHMiOnsiZW5hYmxlZCI6dHJ1ZSwic2VydmVyX25hbWUiOiJleGFtcGxlLmNvbSIsImluc2VjdXJlIjpmYWxzZX19XSwicm91dGUiOnsicnVsZXMiOlt7InR5cGUiOiJzZWxlY3RvciIsInRhZyI6InByb3h5Iiwib3V0Ym91bmRzIjpbImh5c3RlcmlhLTAiXX1dfX0"

# 添加填充
missing_padding = len(encoded) % 4
if missing_padding:
    encoded += '=' * (4 - missing_padding)

# 解码
decoded = base64.urlsafe_b64decode(encoded)
config = json.loads(decoded)

print("Sing-box 配置验证:")
print(json.dumps(config, indent=2, ensure_ascii=False))

print("\n验证结果:")
print(f"[OK] Outbound类型: {config['outbounds'][0]['type']}")
print(f"[OK] 服务器: {config['outbounds'][0]['server']}:{config['outbounds'][0]['server_port']}")
print(f"[OK] 密码: {config['outbounds'][0]['password']}")
print(f"[OK] TLS启用: {config['outbounds'][0]['tls']['enabled']}")
print(f"[OK] SNI: {config['outbounds'][0]['tls']['server_name']}")
print(f"[OK] 路由规则: {len(config['route']['rules'])} 条")