import json
import base64
import os
from typing import List, Dict, Any, Optional


def generate_singbox_url(nodes: List[Dict[str, Any]], options: Optional[Dict[str, Any]] = None) -> str:
    """
    从节点列表生成 Sing-box 配置，并返回 URL 安全的 Base64 字符串。

    :param nodes: 已解析的节点列表（由 hysteria2_parser 提供）
    :param options: 可选生成参数，优先级高于环境变量，支持：
        - rules_preset: 规则预设（cn_direct/global_direct/global_proxy/proxy_domains_only/direct_domains_only）
        - enable_adblock: 是否开启广告域名拦截
        - enable_doh_direct: 是否将常见 DoH 域名直连
        - strict_global_proxy: 是否显式 geosite:geolocation-!cn 走代理
        - bypass_domains: 直连域名（逗号分隔字符串）
        - proxy_domains: 代理域名（逗号分隔字符串）
        - default_alpn: 默认 ALPN（如 "h3" 或 "h2,h3"），仅在节点未提供 alpn 时生效
    :return: base64(JSON config) 去除尾部 = 的 URL 安全字符串
    :raises ValueError: 无节点时报错
    """
    if not nodes:
        raise ValueError("没有节点可生成配置")

    options = options or {}

    outbounds: List[Dict[str, Any]] = []
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
                "insecure": bool(node['insecure']),
            }
        }
        if node.get('sni'):
            outbound["tls"]["server_name"] = node.get('sni')

        # Obfs：仅在 salamander 且提供密码时写入
        obfs_type = (node.get('obfs') or '').strip().lower() if node.get('obfs') else ''
        obfs_pwd = node.get('obfs_password')
        if obfs_type == 'salamander' and obfs_pwd:
            outbound["obfs"] = {"type": "salamander", "password": obfs_pwd}

        # ALPN：优先节点自带；否则 options.default_alpn；最后 DEFAULT_ALPN
        if node.get('alpn'):
            outbound["tls"]["alpn"] = node['alpn']
        else:
            opt_alpn = str(options.get("default_alpn") or "").strip()
            if opt_alpn:
                outbound["tls"]["alpn"] = [p.strip() for p in opt_alpn.split(',') if p.strip()]
            else:
                default_alpn = os.getenv("DEFAULT_ALPN", "h3").strip()
                if default_alpn:
                    outbound["tls"]["alpn"] = [p.strip() for p in default_alpn.split(',') if p.strip()]

        # TLS 证书（PEM 文本或 base64(PEM)）
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
                    outbound["tls"]["certificate"] = [line for line in pem_text.splitlines()]
            except Exception:
                pass

        outbounds.append(outbound)

    # 汇聚出站，方便客户端选择
    selector_outs = [ob['tag'] for ob in outbounds]
    selector = {
        "type": "selector",
        "tag": "proxy",
        "outbounds": selector_outs,
        "default": selector_outs[0] if selector_outs else None,
    }

    # 基础直连（私网）
    rules: List[Dict[str, Any]] = [
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

    # 读取请求/环境配置（请求优先）
    preset = (options.get("rules_preset") or os.getenv("RULES_PRESET", "")).strip().lower()
    enable_cn_rules_env = os.getenv("ENABLE_CN_RULES", "").lower() in ("1", "true", "yes", "on")
    enable_adblock = options.get("enable_adblock") if options.get("enable_adblock") is not None else os.getenv("ENABLE_ADBLOCK", "").lower() in ("1", "true", "yes", "on")
    enable_doh_direct = options.get("enable_doh_direct") if options.get("enable_doh_direct") is not None else os.getenv("ENABLE_DOH_DIRECT", "").lower() in ("1", "true", "yes", "on")
    strict_global_proxy = options.get("strict_global_proxy") if options.get("strict_global_proxy") is not None else os.getenv("STRICT_GLOBAL_PROXY", "").lower() in ("1", "true", "yes", "on")
    use_rule_set = options.get("use_rule_set") if options.get("use_rule_set") is not None else os.getenv("USE_RULE_SET", "1").lower() in ("1", "true", "yes", "on")

    bypass_str = options.get("bypass_domains") if options.get("bypass_domains") is not None else os.getenv("BYPASS_DOMAINS", "")
    proxy_str = options.get("proxy_domains") if options.get("proxy_domains") is not None else os.getenv("PROXY_DOMAINS", "")
    bypass_domains = [d.strip() for d in (bypass_str or "").split(',') if d.strip()]
    proxy_domains = [d.strip() for d in (proxy_str or "").split(',') if d.strip()]

    # 预设
    rule_sets: List[Dict[str, Any]] = []
    rs_base = os.getenv("RULE_SET_BASE", "https://raw.githubusercontent.com/Loyalsoldier/sing-box-rules/release/rule-set").rstrip('/')
    def _rs(url_name: str, tag: str) -> Dict[str, Any]:
        return {
            "type": "remote",
            "format": "binary",
            "url": f"{rs_base}/{url_name}",
            "tag": tag,
            "download_detour": "proxy",
            "update_interval": "168h",
        }

    if enable_cn_rules_env or preset in ("cn_direct", "cn-direct", "cn"):
        if use_rule_set:
            # 使用远程 rule-set，避免 geosite/geoip 弃用警告
            rule_sets.append(_rs("geoip-cn.srs", "geoip-cn"))
            rule_sets.append(_rs("geosite-geolocation-cn.srs", "geosite-geolocation-cn"))
            rules.extend([
                {"outbound": "direct", "rule_set": ["geoip-cn"]},
                {"outbound": "direct", "rule_set": ["geosite-geolocation-cn"]},
            ])
        else:
            # 回退：仍使用 geosite/geoip（可能出现弃用警告）
            rules.extend([
                {"outbound": "direct", "geoip": ["cn"]},
                {"outbound": "direct", "geosite": ["geolocation-cn", "cn"]},
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

    # 广告拦截与 DoH 直连
    if enable_adblock:
        if use_rule_set:
            rule_sets.append(_rs("geosite-category-ads-all.srs", "ads-all"))
            rules.append({"outbound": "block", "rule_set": ["ads-all"]})
        else:
            rules.append({"outbound": "block", "geosite": ["category-ads-all"]})
    if enable_doh_direct:
        rules.append({"outbound": "direct", "domain": [
            "dns.google",
            "cloudflare-dns.com",
            "one.one.one.one",
            "doh.pub",
            "dns.alidns.com",
        ]})

    # 严格全局代理（确保非 CN 显式走代理）
    if strict_global_proxy:
        if use_rule_set:
            rule_sets.append(_rs("geosite-geolocation-!cn.srs", "geolocation-not-cn"))
            rules.append({"outbound": "proxy", "rule_set": ["geolocation-not-cn"]})
        else:
            # 显式将非 CN 域名走代理
            rules.append({"outbound": "proxy", "geosite": ["geolocation-!cn"]})

    # 自定义直连/代理域名（与“仅*域名”预设互斥追加）
    if bypass_domains and preset not in ("proxy_domains_only", "proxy_only"):
        rules.append({"outbound": "direct", "domain": bypass_domains})
    if proxy_domains and preset not in ("direct_domains_only", "bypass_only"):
        rules.append({"outbound": "proxy", "domain": proxy_domains})

    route = {
        "rules": rules,
        "final": final_tag,
    }
    if use_rule_set and rule_sets:
        route["rule_set"] = rule_sets

    # 如启用广告拦截，提供 block 出站
    if enable_adblock:
        outbounds.append({"type": "block", "tag": "block"})

    config = {
        "outbounds": outbounds + [selector],
        "route": route,
    }

    # 紧凑且键序稳定的 JSON
    json_str = json.dumps(config, separators=(',', ':'), sort_keys=True)

    # URL 安全 Base64（去除填充）
    encoded = base64.urlsafe_b64encode(json_str.encode('utf-8')).decode('utf-8').rstrip('=')
    return encoded
