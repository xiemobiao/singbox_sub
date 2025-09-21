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

    preset_opt = (options or {}).get("rules_preset") if options else None
    preset_env = os.getenv("RULES_PRESET", "")
    preset = (preset_opt or preset_env or "").strip().lower()
    enable_cn_rules_env = os.getenv("ENABLE_CN_RULES", "").lower() in ("1", "true", "yes", "on")
    enable_doh_direct = (options.get("enable_doh_direct") if options and options.get("enable_doh_direct") is not None else os.getenv("ENABLE_DOH_DIRECT", "").lower() in ("1", "true", "yes", "on"))
    strict_global_proxy = (options.get("strict_global_proxy") if options and options.get("strict_global_proxy") is not None else os.getenv("STRICT_GLOBAL_PROXY", "").lower() in ("1", "true", "yes", "on"))
    bypass_env = os.getenv("BYPASS_DOMAINS", "")
    proxy_env = os.getenv("PROXY_DOMAINS", "")
    bypass_str = (options.get("bypass_domains") if options else None) or bypass_env
    proxy_str = (options.get("proxy_domains") if options else None) or proxy_env
    bypass_domains = [d.strip() for d in (bypass_str or "").split(",") if d.strip()]
    proxy_domains = [d.strip() for d in (proxy_str or "").split(",") if d.strip()]

    if enable_cn_rules_env or preset in ("cn_direct", "cn-direct", "cn"):
        rules.extend([
            {"outbound": "direct", "ip_cidr": ["geoip:cn"]},
            {"outbound": "direct", "domain": ["geosite:geolocation-cn", "geosite:cn"]},
        ])
        final_tag = "proxy"
    elif preset in ("global_direct", "direct_all", "direct"):
        final_tag = "direct"
    elif preset in ("global_proxy", "proxy_all", "proxy"):
        final_tag = "proxy"
    elif preset in ("proxy_domains_only", "proxy_only"):
        if proxy_domains:
            rules.append({"outbound": "proxy", "domain": proxy_domains})
        final_tag = "direct"
    elif preset in ("direct_domains_only", "bypass_only"):
        if bypass_domains:
            rules.append({"outbound": "direct", "domain": bypass_domains})
        final_tag = "proxy"
    else:
        final_tag = "proxy"

    # 广告拦截（需要 geosite 数据库）：将广告域名导向阻断出站
    enable_adblock = (options.get("enable_adblock") if options and options.get("enable_adblock") is not None else os.getenv("ENABLE_ADBLOCK", "").lower() in ("1", "true", "yes", "on"))
    if enable_adblock:
        rules.append({"outbound": "block", "domain": ["geosite:category-ads-all"]})

    # 明确将非 CN 域名走代理（可选，通常 final=proxy 已满足）
    if strict_global_proxy:
        rules.append({"outbound": "proxy", "domain": ["geosite:geolocation-!cn"]})

    # DoH 常见域名直连（可选）
    if enable_doh_direct:
        rules.append({"outbound": "direct", "domain": [
            "dns.google",
            "cloudflare-dns.com",
            "one.one.one.one",
            "doh.pub",
            "dns.alidns.com",
        ]})

    # 自定义直连/代理域名（逗号分隔）
    if bypass_domains and preset not in ("proxy_domains_only", "proxy_only"):
        rules.append({"outbound": "direct", "domain": bypass_domains})

    if proxy_domains and preset not in ("direct_domains_only", "bypass_only"):
        rules.append({"outbound": "proxy", "domain": proxy_domains})

    route = {
        "rules": rules,
        "final": final_tag,
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
