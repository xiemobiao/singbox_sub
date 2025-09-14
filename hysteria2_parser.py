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
    - 必需：password
    - 可选：sni/server_name, insecure(1/true/yes/on), obfs(type), obfs-password(或 salamander 直接作为密码), alpn(逗号分隔), ca
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

            params = urllib.parse.parse_qs(parsed_url.query)

            # 必需: password（支持在 userinfo 中或 query 中）
            password = params.get('password', [None])[0]
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
                params.get('sni', [None])[0]
                or params.get('server_name', [None])[0]
                or params.get('peer', [None])[0]
            )

            insecure_raw = (params.get('insecure', ['0'])[0] or '').strip().lower()
            insecure = insecure_raw in ('1', 'true', 'yes', 'on')

            # Obfs: type + password
            obfs_type = params.get('obfs', [None])[0]
            obfs_password = params.get('obfs-password', [None])[0]
            # 某些分享可能直接用 salamander=xxx 表示密码
            if not obfs_password:
                obfs_password = params.get('salamander', [None])[0]

            # ALPN: 逗号分隔 -> 数组
            alpn_raw = params.get('alpn', [None])[0]
            alpn_list = None
            if alpn_raw:
                alpn_list = [p.strip() for p in alpn_raw.split(',') if p.strip()]

            ca = params.get('ca', [None])[0]

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
            }
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
