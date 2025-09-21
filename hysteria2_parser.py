import base64
import urllib.parse
import requests
from typing import List, Dict, Any

def parse_hysteria2_subscription(subscription: str) -> List[Dict[str, Any]]:
    """
    解析 Hysteria2/Hy2 订阅内容，返回节点列表。

    支持：
    - 订阅链接（http/https）指向的文本
    - 多行订阅（每行一个 URI 或每行一个 base64 编码的 URI）
    - 整段 base64 的订阅（解码后为多行 URI）
    - scheme: hysteria2:// 或 hy2://

    参数映射：
    - 必需：password（可在 userinfo 或 query 中）
    - 可选：
      - SNI：sni/server_name/peer/peername/host/hostname
      - 不校验证书：insecure/allow-insecure/allowInsecure/skip-cert-verify（1/true/yes/on）或 verify=0
      - 混淆：obfs（仅支持 salamander），obfs-password（或 salamander= 作为密码）
      - ALPN：alpn（逗号分隔）
      - 证书：ca（PEM 文本或其 base64）
      - 名称：URI 片段（#Name）保存在 name 字段
    """
    try:
        # 如果是URL，获取内容
        if subscription.startswith(('http://', 'https://')):
            response = requests.get(subscription, timeout=10)
            response.raise_for_status()
            content = response.text
        else:
            content = subscription

        content = content.strip()

        # 若整段不含 "://"，尝试整段 base64 解码一次
        def _maybe_b64_decode(s: str) -> str:
            try:
                pad = (-len(s)) % 4
                if pad:
                    s = s + ('=' * pad)
                return base64.b64decode(s).decode('utf-8')
            except Exception:
                return s

        if '://' not in content:
            content = _maybe_b64_decode(content)

        lines = content.splitlines()
        nodes: List[Dict[str, Any]] = []

        for raw in lines:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue

            # 行内容可能本身是 URI，也可能是 base64 编码的 URI
            decoded = line
            if '://' not in decoded:
                decoded_candidate = _maybe_b64_decode(decoded)
                decoded = decoded_candidate

            # 解析URL: hysteria2:// 或 hy2:// server:port?params
            parsed_url = urllib.parse.urlparse(decoded)
            scheme = (parsed_url.scheme or '').lower()
            if scheme not in ('hysteria2', 'hy2'):
                raise ValueError(f"无效的Hysteria2/Hy2 URL: {decoded[:80]}...")

            server = parsed_url.hostname
            port = parsed_url.port
            if not server or port is None:
                raise ValueError(f"无效的服务器/端口: {decoded[:80]}...")

            params_raw = urllib.parse.parse_qs(parsed_url.query)
            # 统一使用小写键，取第一个值
            params: Dict[str, str] = {k.lower(): (v[0] if isinstance(v, list) else v)
                                      for k, v in params_raw.items()}

            # 必需: password（支持在 userinfo 中或 query 中）
            password = params.get('password')
            if not password:
                # 某些分享把密码放在 userinfo（hysteria2://PASSWORD@host:port）
                # urlparse 会解析为 username 字段
                try:
                    ui = parsed_url.username
                    if ui:
                        password = urllib.parse.unquote(ui)
                except Exception:
                    pass
            if not password:
                raise ValueError(f"缺少password参数: {decoded[:80]}...")

            # 可选参数
            # 兼容部分实现使用 peer 作为 SNI 的情况
            sni = (
                params.get('sni')
                or params.get('server_name')
                or params.get('peer')
                or params.get('peername')
                or params.get('host')
                or params.get('hostname')
            )

            def _truthy(val: str | None) -> bool:
                if val is None:
                    return False
                return val.strip().lower() in ('1', 'true', 'yes', 'on')

            def _falsy(val: str | None) -> bool:
                if val is None:
                    return False
                return val.strip().lower() in ('0', 'false', 'no', 'off')

            insecure = (
                _truthy(params.get('insecure'))
                or _truthy(params.get('allow-insecure'))
                or _truthy(params.get('allowinsecure'))
                or _truthy(params.get('skip-cert-verify'))
                or _falsy(params.get('verify'))  # verify=0 等价于 insecure
            )

            # Obfs: type + password
            obfs_type = params.get('obfs')
            obfs_password = params.get('obfs-password')
            # 某些分享可能直接用 salamander=xxx 表示密码
            if not obfs_password:
                obfs_password = params.get('salamander')

            # ALPN: 逗号分隔 -> 数组
            alpn_raw = params.get('alpn')
            alpn_list = None
            if alpn_raw:
                alpn_list = [p.strip() for p in alpn_raw.split(',') if p.strip()]

            ca = params.get('ca')

            # 端口跳跃（mport），形如 30000-31000 或 30000:31000
            mport_raw = params.get('mport') or params.get('multiport')
            server_ports = None
            if mport_raw:
                rng = mport_raw.strip().replace(' ', '')
                if '-' in rng:
                    a, b = rng.split('-', 1)
                    if a.isdigit() and b.isdigit():
                        server_ports = [f"{int(a)}:{int(b)}"]
                elif ':' in rng:
                    a, b = rng.split(':', 1)
                    if a.isdigit() and b.isdigit():
                        server_ports = [f"{int(a)}:{int(b)}"]

            # 名称（来自 URI 片段 #name）
            name = urllib.parse.unquote(parsed_url.fragment) if parsed_url.fragment else None

            node = {
                'server': server,
                'port': port,
                'password': password,
                'sni': sni,
                'insecure': insecure,
                'obfs': obfs_type,
                'obfs_password': obfs_password,
                'alpn': alpn_list,
                'ca': ca,
                'name': name,
            }
            if server_ports:
                node['server_ports'] = server_ports
            nodes.append(node)

        if not nodes:
            raise ValueError("订阅中没有有效节点")

        return nodes

    except requests.RequestException as e:
        raise ValueError(f"获取订阅URL失败: {e}")
    except ValueError:
        raise  # 重新抛出ValueError
    except Exception as e:
        raise ValueError(f"解析订阅时发生未知错误: {e}")
