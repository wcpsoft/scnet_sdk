"""SCNet 容器 API 同步客户端。

覆盖文档中的容器相关能力：
- 查询节点资源限额（创建前确认配额）
- 创建容器实例
- 查询容器实例详情 / 执行状态
- 批量执行脚本
- 批量删除容器

异步版本见 :class:`scnet_sdk.aclient.AsyncScnetClient`（能力与语义完全对齐）。

最简用法::

    from scnet_sdk import ScnetClient, ContainerSpec

    with ScnetClient.from_config('scnet.yaml') as client:
        container_id = client.create_container(ContainerSpec(...))
        info = client.wait_for_container(container_id)
        client.delete_containers([container_id])
"""
from __future__ import annotations

import time
import warnings
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence, Tuple, Union

import httpx

from ._http import api_request
from .auth import fetch_center, obtain_credentials, resolve_ai_url
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
from .models import ContainerInfo, ContainerSpec, ResourceLimits


class ScnetClient(ScnetClientBase):
    """同步容器 API 客户端。

    参数
    ----
    config:
        已构造的 :class:`~scnet_sdk.config.ScnnetConfig`。留空时按 config_path /
        用户态 YAML / 环境变量自动加载。
    token / ai_url / request_timeout / wait_timeout / poll_interval /
    running_statuses / terminal_statuses:
        对配置的单项覆盖，优先级最高。
    config_path:
        用户态 YAML 路径（等价于环境变量 `SCNET_CONFIG`）。
    search_user_config:
        是否按默认顺序搜索用户态配置文件（`./scnet.yaml`、`~/.config/scnet/...`）。
    use_environment:
        是否允许 `SCNET_*` 环境变量覆盖配置。
    http_client:
        复用外部 `httpx.Client`（例如注入 MockTransport 做测试）。
    """

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
        http_client: Optional[httpx.Client] = None,
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
        self._http = http_client or httpx.Client()

    # ------------------------------------------------------------ 构造/生命周期
    @classmethod
    def from_config(
        cls,
        config_path: Optional[str] = None,
        *,
        config: Optional[ScnetConfig] = None,
        require_credentials: bool = True,
        http_client: Optional[httpx.Client] = None,
        **config_kwargs: Any,
    ) -> 'ScnetClient':
        """按配置创建客户端；配置中带 AK/SK 时自动完成两步认证。

        可传 `config_path`（用户态 YAML 路径）或已构造好的 `config` 对象；
        `config_kwargs` 会传给 :meth:`ScnetConfig.load`（例如 `env=`、`cwd=`、
        `use_environment=False`，或直接给 `cluster_id='11112'` 之类的覆盖项）。
        """
        if config is not None:
            if config_kwargs:
                raise ScnetConfigError('config 与其它配置关键字不能同时使用')
        else:
            config = ScnetConfig.load(config_path, **config_kwargs)
        return cls._from_config(
            config, require_credentials=require_credentials, http_client=http_client
        )

    @classmethod
    def _from_config(
        cls,
        config: ScnetConfig,
        *,
        require_credentials: bool = True,
        http_client: Optional[httpx.Client] = None,
    ) -> 'ScnetClient':
        plan = auth_plan(config)
        # 有 token 即可工作（ai_url 缺失时首次调用自动解析）；未要求凭证时不主动认证
        if plan == 'token' or not require_credentials:
            return cls(config, http_client=http_client)

        if plan == 'credentials':
            credentials = obtain_credentials(
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
    def from_credentials(
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
        http_client: Optional[httpx.Client] = None,
    ) -> 'ScnetClient':
        """显式用 AK/SK 认证并创建客户端。"""
        return cls._with_credentials(
            user,
            access_key,
            secret_key,
            cluster_id=cluster_id,
            config=config,
            config_path=config_path,
            search_user_config=search_user_config,
            use_environment=use_environment,
            http_client=http_client,
        )

    @classmethod
    def _with_credentials(
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
        http_client: Optional[httpx.Client] = None,
    ) -> 'ScnetClient':
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
        return cls._from_config(base, http_client=http_client)

    @classmethod
    def from_environment(
        cls,
        *,
        env: Optional[Mapping[str, str]] = None,
        **client_kwargs: Any,
    ) -> 'ScnetClient':
        """完全依赖 `SCNET_*` 环境变量创建客户端（默认不搜索用户态配置文件）。"""
        client_kwargs.setdefault('search_user_config', False)
        return cls.from_config(env=env, **client_kwargs)

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> 'ScnetClient':
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---------------------------------------------------------------- 认证刷新
    def refresh_credentials(self) -> Optional[str]:
        """重新认证并刷新 token 与 ai_url，返回新的 token。"""
        config = self.config
        if not (config.user and config.access_key and config.secret_key):
            self._ai_url = None
            self.ensure_ai_url()
            return self.token

        credentials = obtain_credentials(
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

    def ensure_ai_url(self) -> str:
        """确保已解析容器服务地址，返回以 `/ai` 结尾的地址。"""
        if self._ai_url is None:
            center = fetch_center(
                self._require_token(),
                center_url=self.endpoints.center_url,
                timeout=self.timeouts.request,
                client=self._http,
            )
            self._ai_url = resolve_ai_url(center)
        return self._ai_url

    # ------------------------------------------------------------------ 请求
    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Any = None,
        json_body: Any = None,
        request_timeout: Optional[float] = None,
    ) -> Any:
        return api_request(
            self._http,
            method,
            f'{self.ensure_ai_url()}{path}',
            headers=self._auth_headers(),
            params=params,
            json_body=json_body,
            timeout=self._resolve_timeout(request_timeout),
        )

    # ------------------------------------------------------- 资源限额（前置查询）
    def resource_limits(
        self,
        resource_group: str,
        accelerator_type: str,
        *,
        request_timeout: Optional[float] = None,
    ) -> ResourceLimits:
        """查询节点资源限额（创建前的配额参考）。"""
        if not resource_group or not accelerator_type:
            raise ScnetValidationError('resource_group 与 accelerator_type 均为必填项')
        data = self._send(
            'GET',
            self.paths.resources,
            params={
                'resourceGroup': resource_group,
                'acceleratorType': str(accelerator_type).lower(),
            },
            request_timeout=request_timeout,
        )
        return parse_resource_limits(data)

    # ---------------------------------------------------------------- 创建容器
    def create_container(
        self,
        spec: Union[ContainerSpec, Mapping[str, Any]],
        *,
        request_timeout: Optional[float] = None,
    ) -> str:
        """创建容器实例，返回容器实例 ID（响应 data）。"""
        data = self._send(
            'POST',
            self.paths.task,
            json_body=build_create_payload(spec),
            request_timeout=request_timeout,
        )
        return parse_created_id(data)

    # ---------------------------------------------------- 查询容器详情/执行状态
    def get_container(
        self,
        container_id: str,
        *,
        request_timeout: Optional[float] = None,
    ) -> ContainerInfo:
        """查询容器实例详情（`info.status` 即执行状态）。"""
        data = self._send(
            'GET',
            self.paths.detail_for(require_container_id(container_id)),
            request_timeout=request_timeout,
        )
        return parse_container_info(data)

    # 语义别名：容器「执行状态」查询
    get_container_status = get_container

    def wait_for_container(
        self,
        container_id: str,
        *,
        timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
        running_statuses: Optional[Sequence[str]] = None,
        terminal_statuses: Optional[Sequence[str]] = None,
        on_poll: Optional[Callable[[int, ContainerInfo], None]] = None,
    ) -> ContainerInfo:
        """轮询直到容器进入运行态。

        - `timeout`：等待总时长上限（秒），默认取 `config.timeouts.wait`；
        - `poll_interval`：轮询间隔，默认取 `config.timeouts.poll_interval`；
        - 进入终态集合抛 `ScnetStateError`，等待超时抛 `ScnetTimeoutError`；
        - `on_poll(attempt, info)` 可用于打印进度。
        """
        running, terminal = self._resolve_statuses(running_statuses, terminal_statuses)
        wait_limit, interval = self._resolve_wait(timeout, poll_interval)

        deadline = time.monotonic() + wait_limit
        attempt = 0
        info: Optional[ContainerInfo] = None
        while True:
            attempt += 1
            info = self.get_container(container_id)
            if on_poll is not None:
                on_poll(attempt, info)
            decision = wait_decision(info, running, terminal)
            if decision == WAIT_READY:
                return info
            if decision == WAIT_TERMINAL:
                raise self._state_error(container_id, info)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise self._timeout_error(container_id, info, wait_limit)
            time.sleep(min(interval, remaining))

    # ---------------------------------------------------------------- 执行脚本
    def execute_script(
        self,
        container_id: str,
        script: str,
        *,
        scope: str = 'all',
        request_timeout: Optional[float] = None,
    ) -> Any:
        """在容器内批量执行脚本。

        `script` 中的多行命令请使用真实换行符；文档要求每行以换行符结尾，
        可用 :func:`scnet_sdk.join_script_lines` 生成。
        """
        return self._send(
            'POST',
            self.paths.execute_script,
            json_body=build_script_body(container_id, script, scope),
            request_timeout=request_timeout,
        )

    # ---------------------------------------------------------------- 删除容器
    def delete_containers(
        self,
        ids: ContainerIdOrIds,
        *,
        request_timeout: Optional[float] = None,
    ) -> Any:
        """批量删除容器（单个 ID 也走批量接口）。"""
        id_list = normalize_ids(ids)
        return self._send(
            'DELETE',
            self.paths.task,
            params=[('ids', item) for item in id_list],
            request_timeout=request_timeout,
        )

    def delete_container(
        self,
        container_id: str,
        *,
        request_timeout: Optional[float] = None,
    ) -> Any:
        """删除单个容器。"""
        return self.delete_containers([container_id], request_timeout=request_timeout)

    # ------------------------------------------------------- 便捷：临时容器生命周期
    @contextmanager
    def open_container(
        self,
        spec: Union[ContainerSpec, Mapping[str, Any]],
        *,
        wait: bool = True,
        wait_timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
        keep: bool = False,
        on_poll: Optional[Callable[[int, ContainerInfo], None]] = None,
    ) -> Iterator['ContainerHandle']:
        """创建容器并在退出时自动删除（`keep=True` 可保留）。"""
        container_id = self.create_container(spec)
        handle = ContainerHandle(self, container_id)
        try:
            if wait:
                handle.wait(
                    timeout=wait_timeout, poll_interval=poll_interval, on_poll=on_poll
                )
            yield handle
        finally:
            if not keep:
                try:
                    self.delete_containers([container_id])
                except ScnetError as exc:  # 删除失败不掩盖业务异常，仅提示人工清理
                    warnings.warn(
                        f'容器 {container_id} 自动删除失败，请手动清理: {exc}',
                        stacklevel=2,
                    )


class ContainerHandle:
    """绑定同步客户端与容器 ID 的轻量句柄。"""

    def __init__(self, client: ScnetClient, container_id: str):
        self.client = client
        self.id = container_id

    @property
    def info(self) -> ContainerInfo:
        """实时查询容器详情/状态。"""
        return self.client.get_container(self.id)

    @property
    def status(self) -> str:
        """当前状态（每次访问都会请求一次接口）。"""
        return self.info.status

    @property
    def access_urls(self) -> Tuple[str, ...]:
        """容器已公开服务的访问入口。"""
        return self.info.access_urls

    def wait(self, **kwargs: Any) -> ContainerInfo:
        """等待容器进入运行态，参数同 `ScnetClient.wait_for_container`。"""
        return self.client.wait_for_container(self.id, **kwargs)

    def execute(self, script: str, *, scope: str = 'all') -> Any:
        """在容器内执行脚本。"""
        return self.client.execute_script(self.id, script, scope=scope)

    def delete(self) -> Any:
        """删除当前容器。"""
        return self.client.delete_containers([self.id])

    def __str__(self) -> str:
        return f'<ContainerHandle id={self.id}>'
