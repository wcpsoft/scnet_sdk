"""SCNet 容器 API 异步客户端（asyncio）。

与同步客户端 :class:`scnet_sdk.client.ScnnetClient` 能力、语义、请求体完全一致，
区别只在传输层（`httpx.AsyncClient`）与轮询睡眠（`asyncio.sleep`），
可直接用于 FastAPI / asyncio 任务编排而不会阻塞事件循环。

用法::

    import asyncio
    from scnet_sdk import AsyncScnetClient, ContainerSpec

    async def main():
        async with await AsyncScnetClient.from_config('scnet.yaml') as client:
            container_id = await client.create_container(ContainerSpec(...))
            info = await client.wait_for_container(container_id)
            print(info.status)
            await client.delete_containers([container_id])

    asyncio.run(main())
"""
from __future__ import annotations

import asyncio
import time
import warnings
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

import httpx

from ._http import api_request_async
from .auth import fetch_center_async, obtain_credentials_async, resolve_ai_url
from .base import (
    NO_CREDENTIALS_MESSAGE,
    WAIT_READY,
    WAIT_TERMINAL,
    ContainerIdOrIds,
    ScnetClientBase,
    auth_plan,
    build_create_payload,
    build_script_body,
    normalize_ids,
    parse_container_info,
    parse_created_id,
    parse_resource_limits,
    require_container_id,
    wait_decision,
)
from .config import ScnetConfig
from .errors import ScnetConfigError, ScnetError, ScnetValidationError
from .logging import DEBUG, ERROR, INFO, WARNING, log_event
from .models import ContainerInfo, ContainerSpec, ResourceLimits

# 轮询回调可以是同步函数或协程函数
PollCallback = Callable[[int, ContainerInfo], Union[None, Awaitable[None]]]


class AsyncScnetClient(ScnetClientBase):
    """异步容器 API 客户端。

    参数与 :class:`scnet_sdk.client.ScnnetClient` 相同，但 `http_client` 需为
    `httpx.AsyncClient`。注意 `from_config` / `from_credentials` / `from_environment`
    是协程方法，需要 `await`。
    """

    LOGGER_NAME = 'aclient'

    def __init__(
        self,
        config: Optional[ScnetConfig] = None,
        *,
        token: Optional[str] = None,
        ai_url: Optional[str] = None,
        request_timeout: Optional[float] = None,
        wait_timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
        running_statuses: Optional[Sequence[str]] = None,
        terminal_statuses: Optional[Sequence[str]] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        config_path: Optional[str] = None,
        search_user_config: bool = True,
        use_environment: bool = True,
    ):
        super().__init__(
            config,
            token=token,
            ai_url=ai_url,
            request_timeout=request_timeout,
            wait_timeout=wait_timeout,
            poll_interval=poll_interval,
            running_statuses=running_statuses,
            terminal_statuses=terminal_statuses,
            config_path=config_path,
            search_user_config=search_user_config,
            use_environment=use_environment,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient()

    # ------------------------------------------------------------ 构造/生命周期
    @classmethod
    async def from_config(
        cls,
        config_path: Optional[str] = None,
        *,
        config: Optional[ScnetConfig] = None,
        require_credentials: bool = True,
        http_client: Optional[httpx.AsyncClient] = None,
        **config_kwargs: Any,
    ) -> 'AsyncScnetClient':
        """按配置创建客户端；配置中带 AK/SK 时自动完成两步认证（需 await）。"""
        if config is not None:
            if config_kwargs:
                raise ScnetConfigError('config 与其它配置关键字不能同时使用')
        else:
            config = ScnetConfig.load(config_path, **config_kwargs)
        return await cls._from_config(
            config, require_credentials=require_credentials, http_client=http_client
        )

    @classmethod
    async def _from_config(
        cls,
        config: ScnetConfig,
        *,
        require_credentials: bool = True,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> 'AsyncScnetClient':
        plan = auth_plan(config)
        if plan == 'token' or not require_credentials:
            return cls(config, http_client=http_client)

        if plan == 'credentials':
            credentials = await obtain_credentials_async(
                config.user or '',
                config.access_key or '',
                config.secret_key or '',
                cluster_id=config.cluster_id,
                token_url=config.endpoints.token_url,
                center_url=config.endpoints.center_url,
                timeout=config.timeouts.request,
                compact=config.signing_compact,
                client=http_client,
            )
            config = replace(
                config,
                token=credentials.token,
                ai_url=credentials.ai_url,
                cluster_id=credentials.cluster_id,
                sources=config.sources + (f'认证区域 {credentials.cluster_name}',),
            )
            return cls(config, http_client=http_client)

        raise ScnetConfigError(NO_CREDENTIALS_MESSAGE)

    @classmethod
    async def from_credentials(
        cls,
        user: str,
        access_key: str,
        secret_key: str,
        *,
        cluster_id: Optional[str] = None,
        config: Optional[ScnetConfig] = None,
        config_path: Optional[str] = None,
        search_user_config: bool = True,
        use_environment: bool = True,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> 'AsyncScnetClient':
        """显式用 AK/SK 认证并创建客户端（需 await）。"""
        base = config if config is not None else ScnetConfig.load(
            config_path,
            search_user_config=search_user_config,
            use_environment=use_environment,
        )
        base = replace(
            base,
            user=user,
            access_key=access_key,
            secret_key=secret_key,
            cluster_id=cluster_id or base.cluster_id,
            token=None,
            ai_url=None,
            sources=base.sources + ('代码传入 AK/SK',),
        )
        return await cls._from_config(base, http_client=http_client)

    @classmethod
    async def from_environment(
        cls,
        *,
        env: Optional[Mapping[str, str]] = None,
        **client_kwargs: Any,
    ) -> 'AsyncScnetClient':
        """完全依赖 `SCNET_*` 环境变量创建客户端（默认不搜索用户态配置文件）。"""
        client_kwargs.setdefault('search_user_config', False)
        return await cls.from_config(env=env, **client_kwargs)

    async def aclose(self) -> None:
        """关闭内部持有的 `httpx.AsyncClient`（外部注入的不会被关闭）。"""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> 'AsyncScnetClient':
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    # ---------------------------------------------------------------- 认证刷新
    async def refresh_credentials(self) -> Optional[str]:
        """重新认证并刷新 token 与 ai_url，返回新的 token。"""
        config = self.config
        if not (config.user and config.access_key and config.secret_key):
            self._ai_url = None
            await self.ensure_ai_url()
            return self.token

        credentials = await obtain_credentials_async(
            config.user,
            config.access_key,
            config.secret_key,
            cluster_id=config.cluster_id,
            token_url=config.endpoints.token_url,
            center_url=config.endpoints.center_url,
            timeout=config.timeouts.request,
            compact=config.signing_compact,
            client=self._http,
        )
        self.config = replace(
            config,
            token=credentials.token,
            ai_url=credentials.ai_url,
            cluster_id=credentials.cluster_id,
        )
        self.token = credentials.token
        self._ai_url = credentials.ai_url
        return self.token

    async def ensure_ai_url(self) -> str:
        """确保已解析容器服务地址，返回以 `/ai` 结尾的地址。"""
        if self._ai_url is None:
            center = await fetch_center_async(
                self._require_token(),
                center_url=self.endpoints.center_url,
                timeout=self.timeouts.request,
                client=self._http,
            )
            self._ai_url = resolve_ai_url(center)
        return self._ai_url

    # ------------------------------------------------------------------ 请求
    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: Any = None,
        json_body: Any = None,
        request_timeout: Optional[float] = None,
    ) -> Any:
        url = f'{await self.ensure_ai_url()}{path}'
        log_event(self._logger, DEBUG, 'request.start', method=method, url=url)
        started = time.monotonic()
        try:
            data = await api_request_async(
                self._http,
                method,
                url,
                headers=self._auth_headers(),
                params=params,
                json_body=json_body,
                timeout=self._resolve_timeout(request_timeout),
            )
        except ScnetError as exc:
            log_event(
                self._logger,
                ERROR,
                'request.failed',
                method=method,
                url=url,
                code=exc.code or '-',
                error=exc.message,
            )
            raise
        log_event(
            self._logger,
            DEBUG,
            'request.finish',
            method=method,
            url=url,
            elapsed_ms=round((time.monotonic() - started) * 1000, 1),
        )
        return data

    # ------------------------------------------------------- 资源限额（前置查询）
    async def resource_limits(
        self,
        resource_group: str,
        accelerator_type: str,
        *,
        request_timeout: Optional[float] = None,
    ) -> ResourceLimits:
        """查询节点资源限额（创建前的配额参考）。"""
        if not resource_group or not accelerator_type:
            raise ScnetValidationError('resource_group 与 accelerator_type 均为必填项')
        data = await self._send(
            'GET',
            self.paths.resources,
            params={
                'resourceGroup': resource_group,
                'acceleratorType': str(accelerator_type).lower(),
            },
            request_timeout=request_timeout,
        )
        limits = parse_resource_limits(data)
        log_event(
            self._logger,
            INFO,
            'limits.ok',
            resource_group=resource_group,
            cpu_number=limits.cpu_number,
            gpu_number=limits.gpu_number,
            memory_size=limits.memory_size,
            max_time=limits.max_time,
        )
        return limits

    # ---------------------------------------------------------------- 创建容器
    async def create_container(
        self,
        spec: Union[ContainerSpec, Mapping[str, Any]],
        *,
        request_timeout: Optional[float] = None,
    ) -> str:
        """创建容器实例，返回容器实例 ID（响应 data）。"""
        payload = build_create_payload(spec)
        log_event(
            self._logger,
            DEBUG,
            'container.create.start',
            name=payload.get('instanceServiceName'),
            task_type=payload.get('taskType'),
            accelerator_type=payload.get('acceleratorType'),
            cpu_number=payload.get('cpuNumber'),
            ram_size=payload.get('ramSize'),
            gpu_number=payload.get('gpuNumber'),
        )
        data = await self._send(
            'POST',
            self.paths.task,
            json_body=payload,
            request_timeout=request_timeout,
        )
        container_id = parse_created_id(data)
        log_event(
            self._logger, INFO, 'container.create.ok', container_id=container_id
        )
        return container_id

    # ---------------------------------------------------- 查询容器详情/执行状态
    async def get_container(
        self,
        container_id: str,
        *,
        request_timeout: Optional[float] = None,
    ) -> ContainerInfo:
        """查询容器实例详情（`info.status` 即执行状态）。"""
        data = await self._send(
            'GET',
            self.paths.detail_for(require_container_id(container_id)),
            request_timeout=request_timeout,
        )
        info = parse_container_info(data)
        log_event(
            self._logger,
            DEBUG,
            'container.detail',
            container_id=container_id,
            status=info.status,
        )
        return info

    # 语义别名：容器「执行状态」查询
    get_container_status = get_container

    async def wait_for_container(
        self,
        container_id: str,
        *,
        timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
        running_statuses: Optional[Sequence[str]] = None,
        terminal_statuses: Optional[Sequence[str]] = None,
        on_poll: Optional[PollCallback] = None,
    ) -> ContainerInfo:
        """轮询直到容器进入运行态（不阻塞事件循环）。

        参数语义与同步版 `ScnetClient.wait_for_container` 完全一致；
        `on_poll` 可以是普通函数，也可以是协程函数。
        """
        running, terminal = self._resolve_statuses(running_statuses, terminal_statuses)
        wait_limit, interval = self._resolve_wait(timeout, poll_interval)

        loop_time = asyncio.get_running_loop().time
        started = loop_time()
        deadline = started + wait_limit
        attempt = 0
        info: Optional[ContainerInfo] = None
        while True:
            attempt += 1
            info = await self.get_container(container_id)
            log_event(
                self._logger,
                DEBUG,
                'container.wait.poll',
                container_id=container_id,
                attempt=attempt,
                status=info.status,
            )
            if on_poll is not None:
                result = on_poll(attempt, info)
                if asyncio.iscoroutine(result):
                    await result
            decision = wait_decision(info, running, terminal)
            if decision == WAIT_READY:
                log_event(
                    self._logger,
                    INFO,
                    'container.wait.ready',
                    container_id=container_id,
                    status=info.status,
                    elapsed_ms=round((loop_time() - started) * 1000, 1),
                )
                return info
            if decision == WAIT_TERMINAL:
                log_event(
                    self._logger,
                    ERROR,
                    'container.wait.terminal',
                    container_id=container_id,
                    status=info.status,
                )
                raise self._state_error(container_id, info)
            remaining = deadline - loop_time()
            if remaining <= 0:
                log_event(
                    self._logger,
                    ERROR,
                    'container.wait.timeout',
                    container_id=container_id,
                    status=info.status,
                    wait_limit=wait_limit,
                )
                raise self._timeout_error(container_id, info, wait_limit)
            await asyncio.sleep(min(interval, remaining))

    # ---------------------------------------------------------------- 执行脚本
    async def execute_script(
        self,
        container_id: str,
        script: str,
        *,
        scope: str = 'all',
        request_timeout: Optional[float] = None,
    ) -> Any:
        """在容器内批量执行脚本。"""
        body = build_script_body(container_id, script, scope)
        log_event(
            self._logger,
            DEBUG,
            'container.script.start',
            container_id=container_id,
            scope=body['startScriptActionScope'],
            length=len(script),
        )
        result = await self._send(
            'POST',
            self.paths.execute_script,
            json_body=body,
            request_timeout=request_timeout,
        )
        log_event(self._logger, INFO, 'container.script.ok', container_id=container_id)
        return result

    # ---------------------------------------------------------------- 删除容器
    async def delete_containers(
        self,
        ids: ContainerIdOrIds,
        *,
        request_timeout: Optional[float] = None,
    ) -> Any:
        """批量删除容器（单个 ID 也走批量接口）。"""
        id_list = normalize_ids(ids)
        log_event(self._logger, INFO, 'container.delete.start', ids=id_list)
        result = await self._send(
            'DELETE',
            self.paths.task,
            params=[('ids', item) for item in id_list],
            request_timeout=request_timeout,
        )
        log_event(self._logger, INFO, 'container.delete.ok', count=len(id_list))
        return result

    async def delete_container(
        self,
        container_id: str,
        *,
        request_timeout: Optional[float] = None,
    ) -> Any:
        """删除单个容器。"""
        return await self.delete_containers([container_id], request_timeout=request_timeout)

    # ------------------------------------------------------- 便捷：临时容器生命周期
    @asynccontextmanager
    async def open_container(
        self,
        spec: Union[ContainerSpec, Mapping[str, Any]],
        *,
        wait: bool = True,
        wait_timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
        keep: bool = False,
        on_poll: Optional[PollCallback] = None,
    ) -> AsyncIterator['AsyncContainerHandle']:
        """创建容器并在退出时自动删除（`keep=True` 可保留）。"""
        container_id = await self.create_container(spec)
        handle = AsyncContainerHandle(self, container_id)
        try:
            if wait:
                await handle.wait(
                    timeout=wait_timeout, poll_interval=poll_interval, on_poll=on_poll
                )
            yield handle
        finally:
            if keep:
                log_event(self._logger, INFO, 'container.keep', container_id=container_id)
            else:
                try:
                    await self.delete_containers([container_id])
                except ScnetError as exc:  # 删除失败不掩盖业务异常，仅提示人工清理
                    log_event(
                        self._logger,
                        WARNING,
                        'container.cleanup.failed',
                        container_id=container_id,
                        error=exc.message,
                    )
                    warnings.warn(
                        f'容器 {container_id} 自动删除失败，请手动清理: {exc}',
                        stacklevel=2,
                    )


class AsyncContainerHandle:
    """绑定异步客户端与容器 ID 的轻量句柄。

    与同步 `ContainerHandle` 的差异：`info` / `status` / `access_urls`
    需要 IO，因此是协程方法而非属性。
    """

    def __init__(self, client: AsyncScnetClient, container_id: str):
        self.client = client
        self.id = container_id

    async def info(self) -> ContainerInfo:
        """实时查询容器详情/状态。"""
        return await self.client.get_container(self.id)

    async def status(self) -> str:
        """当前状态（每次调用都会请求一次接口）。"""
        return (await self.info()).status

    async def access_urls(self) -> Tuple[str, ...]:
        """容器已公开服务的访问入口。"""
        return (await self.info()).access_urls

    async def wait(self, **kwargs: Any) -> ContainerInfo:
        """等待容器进入运行态，参数同 `AsyncScnetClient.wait_for_container`。"""
        return await self.client.wait_for_container(self.id, **kwargs)

    async def execute(self, script: str, *, scope: str = 'all') -> Any:
        """在容器内执行脚本。"""
        return await self.client.execute_script(self.id, script, scope=scope)

    async def delete(self) -> Any:
        """删除当前容器。"""
        return await self.client.delete_containers([self.id])

    def __str__(self) -> str:
        return f'<AsyncContainerHandle id={self.id}>'
