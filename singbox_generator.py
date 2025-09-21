import json
import base64
import os
from typing import List, Dict, Any, Optional

def generate_singbox_url(nodes: List[Dict[str, Any]], options: Optional[Dict[str, Any]] = None) -> str:
    """
    从节点列表生成 Sing-box 配置的 base64（URL-safe）。

    :param nodes: 解析后的节点列表
    :return: base64(JSON config)，可直接用于 sing-box 订阅导入
    :raises ValueError: 无节点
    """
    if not nodes:
        raise ValueError("没有节点可生成配置")
    
    outbounds = []
    for i, node in enumerate(nodes):
        tag = node.get('name') or f"hysteria-{i}"
        outbound: Dict[str, Any] = {
            "type": "hysteria2",
            "tag": tag,
            "server": node['server'],
            "server_port": node['port'],
            "password": node['password'],
            "tls": {
                "enabled": True,
                # server_name 在无 SNI 时不要写入 None，避免客户端不兼容
                "insecure": bool(node['insecure']),
            }
        }
        if node.get('sni'):
            outbound["tls"]["server_name"] = node.get('sni')
        
        # Obfs: 仅在类型为 salamander 且提供密码时写入
        obfs_type = (node.get('obfs') or '').strip().lower() if node.get('obfs') else ''
        obfs_pwd = node.get('obfs_password')
        if obfs_type == 'salamander' and obfs_pwd:
            outbound["obfs"] = {"type": "salamander", "password": obfs_pwd}
        
        # ALPN（置于 TLS 配置内）
        if node.get('alpn'):
            outbound["tls"]["alpn"] = node['alpn']
        else:
            # 默认提供 h3，兼容多数 hy2 服务端；可用环境变量覆盖/置空
            default_alpn = os.getenv("DEFAULT_ALPN", "h3").strip()
            if default_alpn:
                outbound["tls"]["alpn"] = [p.strip() for p in default_alpn.split(',') if p.strip()]
        
        # 证书（sing-box 出站 TLS 使用 certificate/certificate_path；不使用 ca 字段）
        # 支持：直接提供 PEM 文本，或 base64(PEM)
        if node.get('ca'):
            try:
                ca_val = node['ca']
                pem_text = None
                if isinstance(ca_val, str) and '-----BEGIN' in ca_val:
                    pem_text = ca_val
                else:
                    ca_bytes = base64.b64decode(ca_val)
                    decoded = ca_bytes.decode('utf-8', errors='ignore')
                    if '-----BEGIN' in decoded:
                        pem_text = decoded

                if pem_text:
                    # sing-box 文档描述为“certificate line array”，此处按行切分以提高兼容性
                    outbound["tls"]["certificate"] = [line for line in pem_text.splitlines()]
            except Exception:
                # 若格式无法识别，则忽略证书以避免错误配置
                pass
        
        outbounds.append(outbound)
    
    # 添加 selector 作为可选的聚合出站（放在 outbounds 列表中）
    selector = {
        "type": "selector",
        "tag": "proxy",
        "outbounds": [ob['tag'] for ob in outbounds]
    }
    # 基础路由：私网直连；可选：CN 直连、广告拦截、DoH 直连、自定义直连/代理域名；最终走 proxy
    rules = [
        {
            "outbound": "direct",
            "ip_cidr": [
                "127.0.0.0/8",
                "10.0.0.0/8",
                "172.16.0.0/12",
                "192.168.0.0/16",
                "::1/128",
                "fc00::/7",
                "fe80::/10",
            ],
        },
    ]

    preset = (os.getenv("RULES_PRESET", "").strip().lower())
    if (os.getenv("ENABLE_CN_RULES", "").lower() in ("1", "true", "yes", "on")) or preset in ("cn_direct", "cn-direct", "cn"):
        rules.extend([
            {"outbound": "direct", "ip_cidr": ["geoip:cn"]},
            {"outbound": "direct", "domain": ["geosite:geolocation-cn", "geosite:cn"]},
        ])

    # 广告拦截（需要 geosite 数据库）：将广告域名导向阻断出站
    enable_adblock = os.getenv("ENABLE_ADBLOCK", "").lower() in ("1", "true", "yes", "on")
    if enable_adblock:
        rules.append({"outbound": "block", "domain": ["geosite:category-ads-all"]})

    # 明确将非 CN 域名走代理（可选，通常 final=proxy 已满足）
    if os.getenv("STRICT_GLOBAL_PROXY", "").lower() in ("1", "true", "yes", "on"):
        rules.append({"outbound": "proxy", "domain": ["geosite:geolocation-!cn"]})

    # DoH 常见域名直连（可选）
    if os.getenv("ENABLE_DOH_DIRECT", "").lower() in ("1", "true", "yes", "on"):
        rules.append({"outbound": "direct", "domain": [
            "dns.google",
            "cloudflare-dns.com",
            "one.one.one.one",
            "doh.pub",
            "dns.alidns.com",
        ]})

    # 自定义直连/代理域名（逗号分隔）
    bypass_domains = [d.strip() for d in os.getenv("BYPASS_DOMAINS", "").split(",") if d.strip()]
    if bypass_domains:
        rules.append({"outbound": "direct", "domain": bypass_domains})

    proxy_domains = [d.strip() for d in os.getenv("PROXY_DOMAINS", "").split(",") if d.strip()]
    if proxy_domains:
        rules.append({"outbound": "proxy", "domain": proxy_domains})

    route = {
        "rules": rules,
        "final": "proxy",
    }

    # 如开启广告拦截，提供阻断出站
    if enable_adblock:
        outbounds.append({"type": "block", "tag": "block"})

    config = {
        "outbounds": outbounds + [selector],
        "route": route,
    }
    
    # 紧凑且稳定键序的 JSON，便于生成一致的 base64 输出
    json_str = json.dumps(config, separators=(',', ':'), sort_keys=True)
    
    # Base64 URL安全编码
    encoded = base64.urlsafe_b64encode(json_str.encode('utf-8')).decode('utf-8')
    encoded = encoded.rstrip('=')  # 移除填充以符合URL格式
    
    return encoded
