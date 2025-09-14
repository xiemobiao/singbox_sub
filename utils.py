import logging
import re

def validate_subscription_format(subscription: str):
    """
    基础校验：非空字符串。具体格式交由解析器判定（更宽松，兼容多行）。
    说明：部分订阅为多行 Base64，部分为纯文本 hy2/hysteria2 URI，
    此处不做过严校验以避免误判，由解析环节做细致错误信息。
    """
    if not subscription or not isinstance(subscription, str):
        raise ValueError("订阅不能为空")

    if not subscription.strip():
        raise ValueError("订阅不能为空")

def log_error(message: str):
    """
    记录错误日志
    """
    logging.error(message)

def log_info(message: str):
    """
    记录普通信息日志
    """
    logging.info(message)
