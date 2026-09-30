"""同步与异步客户端共享的配置解析、请求体构造规则与纯逻辑。

- 同步客户端：:class:`scnet_sdk.client.ScnnetClient`
- 异步客户端：:class:`scnet_sdk.aclient.AsyncScnetClient`

两者共用同一份 :class:`~scnet_sdk.config.ScnnetConfig`、模型与异常体系，
只有网络传输与等待轮询的实现不同（`httpx.Client` / `httpx.AsyncClient`）。
"""
from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .auth import normalize_ai_url
from .config import ScnetConfig
from .errors import (
    ScnetConfigError,
    ScnetResponseError,
    ScnetStateError,
    ScnetTimeoutError,
    ScnetValidationError,
)
from .models import SCRIPT_ACTION_SCOPES, ContainerInfo, ContainerSpec, ResourceLimits

ContainerIdOrIds = Union[str, Iterable[str]]

# wait_for_container 单轮判定结果
WAIT_READY = 'ready'
WAIT_TERMINAL = 'terminal'
WAIT_PENDING = 'pending'


# --------------------------------------------------------------- 纯逻辑辅助
def build_create_payload(spec: Union[ContainerSpec, Mapping[str, Any]]) -> dict:
    """把 ContainerSpec（或等价映射）转换为官方请求体。"""
    payload = spec.to_payload() if isinstance(spec, ContainerSpec) else dict(spec)
    if not payload:
        raise ScnetValidationError('创建容器的请求体不能为空')
    return payload


def parse_created_id(data: Any) -> str:
    """解析创建容器返回的容器实例 ID。"""
    if data is None or isinstance(data, (Mapping, list, tuple)):
        raise ScnetResponseError('创建容器未返回容器实例 ID', payload=data)
    return str(data)


def parse_container_info(data: Any) -> ContainerInfo:
    """解析容器实例详情。"""
    if data is not None and not isinstance(data, Mapping):
        raise ScnetResponseError(f'容器详情返回结构非预期: {type(data).__name__}', payload=data)
    return ContainerInfo.from_dict(data or {})


def parse_resource_limits(data: Any) -> ResourceLimits:
    """解析节点资源限额。"""
    if data is not None and not isinstance(data, Mapping):
        raise ScnetResponseError(f'资源限额返回结构非预期: {type(data).__name__}', payload=data)
    return ResourceLimits.from_dict(data or {})


def normalize_ids(ids: ContainerIdOrIds) -> List[str]:
    """规整待删除的容器实例 ID 列表。"""
    if isinstance(ids, str):
        id_list = [ids]
    elif isinstance(ids, Iterable):
        id_list = [str(item) for item in ids]
    else:
        raise ScnetValidationError(f'ids 类型不支持: {type(ids).__name__}')
    id_list = [item for item in id_list if item]
    if not id_list:
        raise ScnetValidationError('ids 不能为空')
    return id_list


def build_script_body(container_id: str, script: str, scope: str) -> dict:
    """构造批量执行脚本的请求体。"""
    if not container_id:
        raise ScnetValidationError('container_id 不能为空')
    if not script:
        raise ScnetValidationError('script 不能为空')
    if str(scope).lower() not in {item.lower() for item in SCRIPT_ACTION_SCOPES}:
        raise ScnetValidationError(
            f'scope={scope!r} 非法，可选值: {list(SCRIPT_ACTION_SCOPES)}'
        )
    return {
        'startScriptActionScope': str(scope).lower(),
        'startScriptContent': script,
        'id': container_id,
    }


def require_container_id(container_id: str) -> str:
    if not container_id:
        raise ScnetValidationError('container_id 不能为空')
    return container_id


def wait_decision(
    info: ContainerInfo,
    running_statuses: Sequence[str],
    terminal_statuses: Sequence[str],
) -> str:
    """根据当前状态判定：就绪 / 终止 / 继续等待。"""
    if info.is_running_with(running_statuses):
        return WAIT_READY
    if info.is_terminal_with(terminal_statuses):
        return WAIT_TERMINAL
    return WAIT_PENDING


def auth_plan(config: ScnetConfig) -> str:
    """判断配置能提供哪种凭证：`token` / `credentials` / `none`。"""
    if config.token:
        return 'token'
    if config.user and config.access_key and config.secret_key:
        return 'credentials'
    return 'none'


NO_CREDENTIALS_MESSAGE = (
    '未找到可用凭证：请在用户态配置中提供 user/access_key/secret_key，'
    '或直接提供 token（可附 ai_url），或设置对应的 SCNET_* 环境变量'
)


# ------------------------------------------------------------------ 公共基类
class ScnetClientBase:
    """客户端公共部分：配置解析、凭证头与等待参数的统一取值。

    子类需要实现网络相关的部分：
    - `_fetch_center_data()`：拉取授权区域信息（用于解析 ai_url）
    - `ensure_ai_url()`：确保容器服务地址已就绪
    - `refresh_credentials()`：重新认证
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
        config_path: Optional[str] = None,
        search_user_config: bool = True,
        use_environment: bool = True,
    ):
        base = config if config is not None else ScnetConfig.load(
            config_path,
            search_user_config=search_user_config,
            use_environment=use_environment,
        )
        self.config = base.with_overrides(
            token=token,
            ai_url=ai_url,
            request_timeout=request_timeout,
            wait_timeout=wait_timeout,
            poll_interval=poll_interval,
            running_statuses=running_statuses,
            terminal_statuses=terminal_statuses,
        )
        self.token: Optional[str] = self.config.token
        self._ai_url = normalize_ai_url(self.config.ai_url) if self.config.ai_url else None

    # ------------------------------------------------------------ 配置快捷访问
    @property
    def paths(self):
        """接口路径配置。"""
        return self.config.paths

    @property
    def timeouts(self):
        """超时配置。"""
        return self.config.timeouts

    @property
    def statuses(self):
        """运行态 / 终态集合。"""
        return self.config.statuses

    @property
    def endpoints(self):
        """认证与授权区域接口地址。"""
        return self.config.endpoints

    @property
    def ai_url(self) -> Optional[str]:
        """当前容器服务地址（可能尚未解析）。"""
        return self._ai_url

    def describe_config(self) -> str:
        """返回脱敏后的配置摘要，便于日志排查。"""
        return self.config.describe()

    # ------------------------------------------------------------------ 内部
    def _require_token(self) -> str:
        if not self.token:
            raise ScnetConfigError(
                '缺少 token，请使用 from_config()/from_credentials() 获取，或在配置中提供 token'
            )
        return self.token

    def _auth_headers(self) -> Mapping[str, str]:
        return {'token': self._require_token(), 'Content-Type': 'application/json'}

    def _resolve_timeout(self, request_timeout: Optional[float]) -> float:
        return self.timeouts.request if request_timeout is None else float(request_timeout)

    def _resolve_statuses(
        self,
        running_statuses: Optional[Sequence[str]],
        terminal_statuses: Optional[Sequence[str]],
    ) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        running = tuple(running_statuses or self.statuses.running)
        terminal = tuple(terminal_statuses or self.statuses.terminal)
        return running, terminal

    def _resolve_wait(self, timeout: Optional[float], poll_interval: Optional[float]) -> Tuple[float, float]:
        wait_limit = self.timeouts.wait if timeout is None else float(timeout)
        interval = self.timeouts.poll_interval if poll_interval is None else float(poll_interval)
        return wait_limit, interval

    def _state_error(self, container_id: str, info: ContainerInfo) -> ScnetStateError:
        return ScnetStateError(
            f'容器 {container_id} 进入终态: {info.status}', payload=info.raw
        )

    def _timeout_error(
        self, container_id: str, info: ContainerInfo, wait_limit: float
    ) -> ScnetTimeoutError:
        return ScnetTimeoutError(
            f'等待容器 {container_id} 就绪超时({wait_limit}s)，最后状态: {info.status}',
            payload=info.raw,
        )

    def __repr__(self) -> str:
        state = 'ready' if (self.token and self._ai_url) else 'incomplete'
        return f'<{type(self).__name__} {state} ai_url={self._ai_url}>'
