"""共享 HTTP 调用与响应解包（同步 + 异步）。

所有 SCNet 开放 API 共用 `{"code": "0", "msg": "...", "data": ...}` 包装结构，
此处统一做：发请求 -> 解析 JSON -> 校验 code -> 返回 data。

- 同步：:func:`api_request`（`httpx.Client`）
- 异步：:func:`api_request_async`（`httpx.AsyncClient`）
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Union

import httpx

from .errors import (
    ScnetApiError,
    ScnetAuthError,
    ScnetResponseError,
    ScnetTransportError,
    describe_code,
)

DEFAULT_TIMEOUT = 30.0
_RAW_TEXT_LIMIT = 512

AnyClient = Union[httpx.Client, httpx.AsyncClient]


def api_request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    params: Any = None,
    json_body: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """同步发送请求并返回业务 `data`；业务错误码非 0 时抛 `ScnetApiError`。"""
    try:
        response = client.request(
            method,
            url,
            headers=dict(headers or {}),
            params=params,
            json=json_body,
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        raise ScnetTransportError(f'请求超时: {method} {url}') from exc
    except httpx.HTTPError as exc:
        raise ScnetTransportError(f'请求失败: {method} {url}: {exc}') from exc

    payload = _decode(response, method, url)
    return _unwrap(payload, method, url, response.status_code)


async def api_request_async(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    params: Any = None,
    json_body: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """异步发送请求，语义与 :func:`api_request` 完全一致。"""
    try:
        response = await client.request(
            method,
            url,
            headers=dict(headers or {}),
            params=params,
            json=json_body,
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        raise ScnetTransportError(f'请求超时: {method} {url}') from exc
    except httpx.HTTPError as exc:
        raise ScnetTransportError(f'请求失败: {method} {url}: {exc}') from exc

    payload = _decode(response, method, url)
    return _unwrap(payload, method, url, response.status_code)


def _decode(response: httpx.Response, method: str, url: str) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        if response.status_code in (401, 403):
            raise ScnetAuthError(
                f'认证失败: {method} {url}', http_status=response.status_code,
                payload=response.text[:_RAW_TEXT_LIMIT],
            ) from exc
        raise ScnetResponseError(
            f'响应不是合法 JSON: {method} {url}',
            http_status=response.status_code,
            payload=response.text[:_RAW_TEXT_LIMIT],
        ) from exc

    if not isinstance(payload, Mapping):
        raise ScnetResponseError(
            f'响应结构非预期: {method} {url}',
            http_status=response.status_code,
            payload=payload,
        )
    return payload


def _unwrap(payload: Mapping[str, Any], method: str, url: str, http_status: int) -> Any:
    if 'code' not in payload:
        raise ScnetResponseError(
            f'响应缺少 code 字段: {method} {url}', http_status=http_status, payload=payload
        )

    code = str(payload.get('code'))
    if code != '0':
        message = payload.get('msg') or describe_code(code)
        raise ScnetApiError(
            f'接口调用失败: {method} {url} -> {message}({describe_code(code)})',
            code=code,
            http_status=http_status,
            payload=payload,
        )
    return payload.get('data')
