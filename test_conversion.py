import base64
import json
import urllib.parse
import requests
from typing import List, Dict, Any

# 复制parser和generator代码到测试文件以避免依赖问题
def parse_hysteria2_subscription(subscription: str) -> List[Dict[str, Any]]:
    try:
        if subscription.startswith('http'):
            response = requests.get(subscription, timeout=10)
            response.raise_for_status()
            content = response.text
        else:
            content = subscription
        
        lines = content.splitlines()
        nodes = []
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            try:
                decoded = base64.b64decode(line).decode('utf-8')
            except (base64.binascii.Error, UnicodeDecodeError):
                raise ValueError(f"无效的Base64编码: {line[:50]}...")
            
            parsed_url = urllib.parse.urlparse(decoded)
            if parsed_url.scheme != 'hysteria2':
                raise ValueError(f"无效的Hysteria2 URL scheme: {decoded[:50]}...")
            
            server = parsed_url.hostname
            port = parsed_url.port
            if not server or port is None:
                raise ValueError(f"无效的服务器/端口: {decoded[:50]}...")
            
            params = urllib.parse.parse_qs(parsed_url.query)
            
            password = params.get('password', [None])[0]
            if not password:
                raise ValueError(f"缺少password参数: {decoded[:50]}...")
            
            sni = params.get('sni', [None])[0]
            insecure = params.get('insecure', ['0'])[0].lower() == '1'
            obfs = params.get('obfs', [None])[0]
            alpn = params.get('alpn', [None])[0]
            ca = params.get('ca', [None])[0]
            
            node = {
                'server': server,
                'port': port,
                'password': password,
                'sni': sni,
                'insecure': insecure,
                'obfs': obfs,
                'alpn': alpn,
                'ca': ca,
            }
            nodes.append(node)
        
        if not nodes:
            raise ValueError("订阅中没有有效节点")
        
        return nodes
    
    except requests.RequestException as e:
        raise ValueError(f"获取订阅URL失败: {e}")

def generate_singbox_url(nodes: List[Dict[str, Any]]) -> str:
    if not nodes:
        raise ValueError("没有节点可生成配置")
    
    outbounds = []
    for i, node in enumerate(nodes):
        outbound = {
            "type": "hysteria2",
            "tag": f"hysteria-{i}",
            "server": node['server'],
            "server_port": node['port'],
            "password": node['password'],
            "up_mbps": 100,
            "down_mbps": 100,
            "tls": {
                "enabled": True,
                "server_name": node.get('sni'),
                "insecure": node['insecure'],
            }
        }
        
        if node.get('obfs'):
            outbound["obfs"] = {
                "type": "salamander",
                "password": node['obfs']
            }
        
        if node.get('alpn'):
            outbound["alpn"] = node['alpn'].split(',')
        
        if node.get('ca'):
            try:
                ca_bytes = base64.b64decode(node['ca'])
                outbound["tls"]["ca"] = ca_bytes.decode('utf-8')
            except Exception:
                pass
        
        outbounds.append(outbound)
    
    config = {
        "outbounds": outbounds,
        "route": {
            "rules": [
                {
                    "type": "selector",
                    "tag": "proxy",
                    "outbounds": [ob['tag'] for ob in outbounds]
                }
            ]
        }
    }
    
    json_str = json.dumps(config, separators=(',', ':'))
    encoded = base64.urlsafe_b64encode(json_str.encode('utf-8')).decode('utf-8').rstrip('=')
    return encoded

if __name__ == "__main__":
    # 示例Hysteria2订阅 (base64 of hysteria2://example.com:443?password=test&sni=example.com)
    example_line = base64.b64encode(b'hysteria2://example.com:443?password=test&sni=example.com').decode('utf-8')
    subscription = example_line
    print("测试订阅:", subscription)
    
    try:
        nodes = parse_hysteria2_subscription(subscription)
        print("解析节点:", nodes)
        singbox_url = generate_singbox_url(nodes)
        print("Sing-box Base64:", singbox_url)
        print("测试成功!")
    except Exception as e:
        print("测试失败:", str(e))
