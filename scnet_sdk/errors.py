"""SCNet OpenAPI 异常定义，保留官方文档中的错误码与说明。

错误码来源：api/scnet 文档「通用错误码」与各接口「错误码」小节。
"""
from __future__ import annotations

from typing import Any, Optional

# 官方文档收录的错误码
ERROR_MESSAGES = {
    '0': '成功',
    '10001': '内部异常（其他异常）',
    '10003': '参数不全',
    '10004': '参数无效',
    '10007': '用户已被冻结',
    '10008': '权限不足',
    '10009': '没有权限访问接口',
    '10010': '文件校验失败',
    '10011': '文件过大',
    '10012': '连接中断',
    '716020': '查询数据库错误',
    '716864': '执行脚本错误',
    '716865': '创建任务错误',
    '716866': '删除任务失败',
    '716870': '实例数量错误',
}


def describe_code(code: Any) -> str:
    """把错误码翻译成官方说明，未收录时返回提示文本。"""
    return ERROR_MESSAGES.get(str(code), '未收录的错误码')


class ScnetError(Exception):
    """SDK 异常基类。"""

    def __init__(
        self,
        message: str,
        *,
        code: Optional[Any] = None,
        http_status: Optional[int] = None,
        payload: Any = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = None if code is None else str(code)
        self.http_status = http_status
        self.payload = payload

    def __str__(self) -> str:
        parts = [self.message]
        if self.code is not None:
            parts.append(f'code={self.code}({describe_code(self.code)})')
        if self.http_status is not None:
            parts.append(f'http_status={self.http_status}')
        return ' | '.join(parts)


class ScnetConfigError(ScnetError):
    """配置缺失或不可用，例如缺少 token、缺少 ai_url。"""


class ScnetValidationError(ScnetError):
    """本地参数校验失败，请求未发出。"""


class ScnetAuthError(ScnetError):
    """认证失败：AK/SK 签名不通过、token 失效或无权限。"""


class ScnetTransportError(ScnetError):
    """网络层错误：连接失败、超时。"""


class ScnetResponseError(ScnetError):
    """响应不是合法 JSON 或结构不符合约定。"""


class ScnetApiError(ScnetError):
    """服务端返回非 0 业务错误码。"""


class ScnetStateError(ScnetError):
    """容器进入了失败终态。"""


class ScnetTimeoutError(ScnetError):
    """等待容器就绪超时。"""
