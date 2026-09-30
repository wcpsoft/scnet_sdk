"""认证与授权区域：AK/SK 签名换取 token，并解析容器服务地址 aiUrls。

对应文档：
- `01-authentication.md` 获取访问凭证 / 获取授权区域

同步与异步各提供一套函数，签名与解析逻辑完全共享：
- 同步：`fetch_tokens` / `fetch_center` / `obtain_credentials`
- 异步：`fetch_tokens_async` / `fetch_center_async` / `obtain_credentials_async`
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterator, Mapping, Optional, Sequence, Tuple

import httpx

from ._http import DEFAULT_TIMEOUT, api_request, api_request_async
from .errors import ScnetAuthError, ScnetConfigError
from .logging import DEBUG, INFO, get_logger, log_event

_LOGGER = get_logger('auth')

DEFAULT_TOKEN_URL = 'https://api.scnet.cn/api/user/v3/tokens'
DEFAULT_CENTER_URL = 'https://www.scnet.cn/ac/openapi/v2/center'

# 平台自身 token 的区域 ID，仅支持平台层面接口，不能调用容器接口
PLATFORM_CLUSTER_ID = '0'
AI_URL_SUFFIX = '/ai'
_TRUTHY = {'true', '1', 'yes', 'y'}


@contextmanager
def _borrowed_client(client: Optional[httpx.Client]) -> Iterator[httpx.Client]:
    """复用外部 client（便于测试注入 transport），否则临时创建一个。"""
    if client is not None:
        yield client
        return
    with httpx.Client() as owned:
        yield owned


@asynccontextmanager
async def _borrowed_async_client(
    client: Optional[httpx.AsyncClient],
) -> AsyncIterator[httpx.AsyncClient]:
    """异步版：复用外部 client，否则临时创建一个。"""
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient() as owned:
        yield owned


# ------------------------------------------------------------------ 签名
def current_timestamp() -> str:
    """当前秒级时间戳（字符串）。"""
    return str(int(time.time()))


def build_sign_message(
    user: str,
    access_key: str,
    timestamp: Any,
    *,
    compact: bool = True,
) -> str:
    """构造待签名消息：`{"accessKey":..,"timestamp":..,"user":..}`。"""
    payload = {
        'accessKey': str(access_key),
        'timestamp': str(timestamp),
        'user': str(user),
    }
    if compact:
        return json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    return json.dumps(payload, ensure_ascii=False)


def build_signature(
    user: str,
    access_key: str,
    secret_key: str,
    timestamp: Any,
    *,
    compact: bool = True,
) -> str:
    """HMAC-SHA256 签名，返回 16 进制字符串。"""
    if not secret_key:
        raise ScnetConfigError('缺少 secretKey(SK)，无法生成签名')
    message = build_sign_message(user, access_key, timestamp, compact=compact)
    return hmac.new(
        str(secret_key).encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def build_token_headers(
    user: str,
    access_key: str,
    secret_key: str,
    *,
    timestamp: Any = None,
    compact: bool = True,
) -> Mapping[str, str]:
    """构造获取访问凭证所需的请求头（含签名）。"""
    if not user or not access_key:
        raise ScnetConfigError('获取访问凭证需要 user 与 accessKey')
    stamp = str(timestamp or current_timestamp())
    return {
        'user': str(user),
        'accessKey': str(access_key),
        'signature': build_signature(user, access_key, secret_key, stamp, compact=compact),
        'timestamp': stamp,
    }


# ------------------------------------------------------------------ 模型
@dataclass(frozen=True)
class ClusterToken:
    """获取访问凭证返回的区域 token。"""

    cluster_id: str
    cluster_name: str
    token: Optional[str]

    @property
    def usable(self) -> bool:
        """账户停用时会返回区域信息但 token 为 null。"""
        return bool(self.token)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'ClusterToken':
        data = data or {}
        return cls(
            cluster_id=str(data.get('clusterId', '')),
            cluster_name=str(data.get('clusterName', '')),
            token=data.get('token'),
        )


@dataclass(frozen=True)
class ScnetCredentials:
    """一次认证得到的可用凭证。"""

    token: str
    cluster_id: str
    cluster_name: str
    ai_url: str


# ------------------------------------------------------- 响应解析与区域选择
def parse_cluster_tokens(data: Any) -> Tuple[ClusterToken, ...]:
    """解析获取访问凭证的 data。"""
    if data is None:
        return ()
    if not isinstance(data, (list, tuple)):
        raise ScnetAuthError(f'获取访问凭证返回结构非预期: {type(data).__name__}', payload=data)
    return tuple(ClusterToken.from_dict(item) for item in data)


def parse_center_data(data: Any) -> Mapping[str, Any]:
    """解析获取授权区域的 data。"""
    if not isinstance(data, Mapping):
        raise ScnetAuthError(f'获取授权区域返回结构非预期: {type(data).__name__}', payload=data)
    return data


def _is_enabled(item: Mapping[str, Any]) -> bool:
    value = item.get('enable', True)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUTHY


def normalize_ai_url(url: str) -> str:
    """规整容器服务地址：确保以 `/ai` 结尾（文档路径为 `{aiUrls}/ai/openapi/...`）。"""
    if not url:
        raise ScnetConfigError('容器服务地址 ai_url 为空')
    clean = str(url).strip().rstrip('/')
    if '{' in clean or '}' in clean:
        raise ScnetConfigError(
            f'容器服务地址仍是文档占位符 {clean!r}，请显式传入真实地址'
        )
    if clean.endswith(AI_URL_SUFFIX):
        return clean
    return clean + AI_URL_SUFFIX


def pick_ai_urls(center_data: Mapping[str, Any]) -> Tuple[str, ...]:
    """从授权区域信息中取出可用的容器服务地址（未规整）。

    文档说明：`aiUrls` 可能返回多组，需按 `enable` 判断可用性。
    文档返回参数表标注为 string，但示例为数组，两种形态都兼容。
    """
    value = (center_data or {}).get('aiUrls')
    if not value:
        return ()
    if isinstance(value, Mapping):
        value = [value]
    items: Sequence[Any] = value if isinstance(value, (list, tuple)) else [value]

    enabled: list = []
    fallback: list = []
    for item in items:
        if isinstance(item, Mapping):
            url = item.get('url')
            if not url:
                continue
            fallback.append(str(url))
            if _is_enabled(item):
                enabled.append(str(url))
        elif item:
            fallback.append(str(item))
            enabled.append(str(item))
    return tuple(enabled or fallback)


def resolve_ai_url(center_data: Mapping[str, Any]) -> str:
    """解析出第一个可用的容器服务地址，并规整为以 `/ai` 结尾。"""
    urls = pick_ai_urls(center_data)
    if not urls:
        raise ScnetConfigError('授权区域信息中未返回 aiUrls，无法定位容器服务地址')
    return normalize_ai_url(urls[0])


def select_cluster(
    tokens: Sequence[ClusterToken],
    cluster_id: Optional[str] = None,
) -> ClusterToken:
    """按区域 ID 选择 token；未指定时取第一个可用的非平台区域。"""
    if cluster_id is not None:
        wanted = str(cluster_id)
        for item in tokens:
            if item.cluster_id == wanted:
                if not item.usable:
                    raise ScnetAuthError(
                        f'区域 {wanted}({item.cluster_name}) 的 token 为 null，账号可能处于停用状态'
                    )
                return item
        raise ScnetAuthError(f'未找到区域 {wanted} 的访问凭证，请确认账号权限')

    for item in tokens:
        if item.usable and item.cluster_id != PLATFORM_CLUSTER_ID:
            return item
    raise ScnetAuthError('没有可用区域 token，请确认账号状态是否已停用')


def build_credentials(
    cluster: ClusterToken,
    center_data: Mapping[str, Any],
) -> ScnetCredentials:
    """由区域 token 与授权区域信息组装凭证。"""
    return ScnetCredentials(
        token=cluster.token or '',
        cluster_id=cluster.cluster_id,
        cluster_name=cluster.cluster_name,
        ai_url=resolve_ai_url(center_data),
    )


# ------------------------------------------------------------------ 同步流程
def fetch_tokens(
    user: str,
    access_key: str,
    secret_key: str,
    *,
    timestamp: Any = None,
    token_url: str = DEFAULT_TOKEN_URL,
    timeout: float = DEFAULT_TIMEOUT,
    compact: bool = True,
    client: Optional[httpx.Client] = None,
) -> Tuple[ClusterToken, ...]:
    """获取访问凭证，返回各区域 token 列表。"""
    headers = build_token_headers(
        user, access_key, secret_key, timestamp=timestamp, compact=compact
    )
    log_event(_LOGGER, DEBUG, 'auth.token.start', user=user, timestamp=headers['timestamp'])
    with _borrowed_client(client) as http:
        data = api_request(http, 'POST', token_url, headers=headers, timeout=timeout)
    tokens = parse_cluster_tokens(data)
    log_event(_LOGGER, INFO, 'auth.token.ok', count=len(tokens))
    return tokens


def fetch_center(
    token: str,
    *,
    center_url: str = DEFAULT_CENTER_URL,
    timeout: float = DEFAULT_TIMEOUT,
    client: Optional[httpx.Client] = None,
) -> Mapping[str, Any]:
    """获取授权区域，返回 data 对象。"""
    if not token:
        raise ScnetConfigError('获取授权区域需要 token')
    headers = {'token': token, 'Content-Type': 'application/json'}
    log_event(_LOGGER, DEBUG, 'auth.center.start')
    with _borrowed_client(client) as http:
        data = api_request(http, 'GET', center_url, headers=headers, timeout=timeout)
    center = parse_center_data(data)
    log_event(
        _LOGGER,
        INFO,
        'auth.center.ok',
        name=center.get('name'),
        ai_url=next((url for url in pick_ai_urls(center) if '{' not in url), None),
    )
    return center


def obtain_credentials(
    user: str,
    access_key: str,
    secret_key: str,
    *,
    cluster_id: Optional[str] = None,
    token_url: str = DEFAULT_TOKEN_URL,
    center_url: str = DEFAULT_CENTER_URL,
    timeout: float = DEFAULT_TIMEOUT,
    compact: bool = True,
    client: Optional[httpx.Client] = None,
) -> ScnetCredentials:
    """两步认证：获取访问凭证 -> 获取授权区域 -> 解析 ai_url。"""
    tokens = fetch_tokens(
        user,
        access_key,
        secret_key,
        token_url=token_url,
        timeout=timeout,
        compact=compact,
        client=client,
    )
    cluster = select_cluster(tokens, cluster_id)
    center = fetch_center(
        cluster.token or '', center_url=center_url, timeout=timeout, client=client
    )
    credentials = build_credentials(cluster, center)
    log_event(
        _LOGGER,
        INFO,
        'auth.ok',
        cluster_id=credentials.cluster_id,
        cluster_name=credentials.cluster_name,
        ai_url=credentials.ai_url,
    )
    return credentials


# ------------------------------------------------------------------ 异步流程
async def fetch_tokens_async(
    user: str,
    access_key: str,
    secret_key: str,
    *,
    timestamp: Any = None,
    token_url: str = DEFAULT_TOKEN_URL,
    timeout: float = DEFAULT_TIMEOUT,
    compact: bool = True,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[ClusterToken, ...]:
    """异步版 :func:`fetch_tokens`。"""
    headers = build_token_headers(
        user, access_key, secret_key, timestamp=timestamp, compact=compact
    )
    log_event(_LOGGER, DEBUG, 'auth.token.start', user=user, timestamp=headers['timestamp'])
    async with _borrowed_async_client(client) as http:
        data = await api_request_async(http, 'POST', token_url, headers=headers, timeout=timeout)
    tokens = parse_cluster_tokens(data)
    log_event(_LOGGER, INFO, 'auth.token.ok', count=len(tokens))
    return tokens


async def fetch_center_async(
    token: str,
    *,
    center_url: str = DEFAULT_CENTER_URL,
    timeout: float = DEFAULT_TIMEOUT,
    client: Optional[httpx.AsyncClient] = None,
) -> Mapping[str, Any]:
    """异步版 :func:`fetch_center`。"""
    if not token:
        raise ScnetConfigError('获取授权区域需要 token')
    headers = {'token': token, 'Content-Type': 'application/json'}
    log_event(_LOGGER, DEBUG, 'auth.center.start')
    async with _borrowed_async_client(client) as http:
        data = await api_request_async(http, 'GET', center_url, headers=headers, timeout=timeout)
    center = parse_center_data(data)
    log_event(
        _LOGGER,
        INFO,
        'auth.center.ok',
        name=center.get('name'),
        ai_url=next((url for url in pick_ai_urls(center) if '{' not in url), None),
    )
    return center


async def obtain_credentials_async(
    user: str,
    access_key: str,
    secret_key: str,
    *,
    cluster_id: Optional[str] = None,
    token_url: str = DEFAULT_TOKEN_URL,
    center_url: str = DEFAULT_CENTER_URL,
    timeout: float = DEFAULT_TIMEOUT,
    compact: bool = True,
    client: Optional[httpx.AsyncClient] = None,
) -> ScnetCredentials:
    """异步版 :func:`obtain_credentials`。"""
    tokens = await fetch_tokens_async(
        user,
        access_key,
        secret_key,
        token_url=token_url,
        timeout=timeout,
        compact=compact,
        client=client,
    )
    cluster = select_cluster(tokens, cluster_id)
    center = await fetch_center_async(
        cluster.token or '', center_url=center_url, timeout=timeout, client=client
    )
    credentials = build_credentials(cluster, center)
    log_event(
        _LOGGER,
        INFO,
        'auth.ok',
        cluster_id=credentials.cluster_id,
        cluster_name=credentials.cluster_name,
        ai_url=credentials.ai_url,
    )
    return credentials
