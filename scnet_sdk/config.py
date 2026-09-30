"""配置加载：类库系统态（随包发布的默认值）+ 用户态（本地 YAML / 环境变量）。

配置分两层
--------
1. **类库系统态**：`scnet_sdk/defaults.yaml`（打包资源，只读），定义接口地址、
   接口路径、超时、容器状态集合等类库级默认值；代码内置 `CODE_DEFAULTS` 作为
   最终兜底，保证 YAML 缺失时仍可用。
2. **用户态**：用户自己的 YAML 文件，提供凭证、区域、以及系统态配置的覆盖项。
   查找顺序：显式传入路径 > `SCNET_CONFIG` > `./scnet.yaml`（或 `.yml`）
   > `~/.config/scnet/scnet.yaml` > `~/.scnet.yaml`。

优先级（低 -> 高）::

    代码内置默认值 < 系统态 defaults.yaml < 用户态 YAML < SCNET_* 环境变量 < 代码传参

合并规则：映射逐层深合并，列表整体替换（不做拼接）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .errors import ScnetConfigError

ENV_PREFIX = 'SCNET_'
CONFIG_ENV_VAR = 'SCNET_CONFIG'
PACKAGED_DEFAULTS_NAME = 'defaults.yaml'
DEFAULT_CONFIG_NAMES = ('scnet.yaml', 'scnet.yml')

# 代码内置兜底（与 defaults.yaml 同构，YAML 缺失/不完整时生效）
CODE_DEFAULTS: Dict[str, Any] = {
    'endpoints': {
        'token_url': 'https://api.scnet.cn/api/user/v3/tokens',
        'center_url': 'https://www.scnet.cn/ac/openapi/v2/center',
    },
    'paths': {
        'resources': '/openapi/v2/instance-service/resources',
        'task': '/openapi/v2/instance-service/task',
        'execute_script': '/openapi/v2/instance-service/task/actions/execute-script',
        'detail': '/openapi/v2/instance-service/{container_id}/detail',
    },
    'timeouts': {
        'request': 30.0,
        'wait': 1800.0,
        'poll_interval': 5.0,
    },
    'statuses': {
        'running': ['running'],
        'terminal': [
            'finished', 'complete', 'completed', 'success', 'succeeded',
            'failed', 'failure', 'error', 'stopped', 'stop', 'canceled', 'cancelled',
        ],
    },
    # 日志系统（log4j 风格）：级别、语言、handler 与分级 logger
    'logging': {
        'level': 'WARNING',
        'language': 'zh_CN',
        'format': 'text',
        'propagate': True,
        'mask_secrets': True,
        'timestamp_format': '%Y-%m-%d %H:%M:%S',
        'catalog': None,
        'console': False,
        'console_stream': 'stderr',
        'file': None,
        'file_max_bytes': 10485760,
        'file_backup_count': 5,
        'handlers': [],
        'loggers': {},
    },
}

# 用户态字段（凭证与区域等）
USER_FIELDS: Tuple[str, ...] = (
    'cluster_id',
    'ai_url',
    'user',
    'access_key',
    'secret_key',
    'token',
    'signing_compact',
)

# 环境变量 -> 配置路径映射（列表类字段支持逗号分隔）
ENV_OVERRIDES: Mapping[str, Tuple[str, ...]] = {
    'SCNET_USER': ('user',),
    'SCNET_ACCESS_KEY': ('access_key',),
    'SCNET_SECRET_KEY': ('secret_key',),
    'SCNET_TOKEN': ('token',),
    'SCNET_AI_URL': ('ai_url',),
    'SCNET_CLUSTER_ID': ('cluster_id',),
    'SCNET_SIGNING_COMPACT': ('signing_compact',),
    'SCNET_TOKEN_URL': ('endpoints', 'token_url'),
    'SCNET_CENTER_URL': ('endpoints', 'center_url'),
    'SCNET_REQUEST_TIMEOUT': ('timeouts', 'request'),
    'SCNET_WAIT_TIMEOUT': ('timeouts', 'wait'),
    'SCNET_POLL_INTERVAL': ('timeouts', 'poll_interval'),
    'SCNET_RUNNING_STATUSES': ('statuses', 'running'),
    'SCNET_TERMINAL_STATUSES': ('statuses', 'terminal'),
    'SCNET_LOG_LEVEL': ('logging', 'level'),
    'SCNET_LOG_LANGUAGE': ('logging', 'language'),
    'SCNET_LOG_FORMAT': ('logging', 'format'),
    'SCNET_LOG_PROPAGATE': ('logging', 'propagate'),
    'SCNET_LOG_CONSOLE': ('logging', 'console'),
    'SCNET_LOG_CONSOLE_STREAM': ('logging', 'console_stream'),
    'SCNET_LOG_FILE': ('logging', 'file'),
    'SCNET_LOG_CATALOG': ('logging', 'catalog'),
    'SCNET_LOG_TIMESTAMP_FORMAT': ('logging', 'timestamp_format'),
}

# `logging` 段含 handler 列表与 logger 映射，结构较复杂，单独校验
_SECTION_FIELDS: Mapping[str, Tuple[str, ...]] = {
    section: tuple(str(key) for key in mapping)
    for section, mapping in CODE_DEFAULTS.items()
    if section != 'logging'
}

_LOGGING_FIELDS: Tuple[str, ...] = tuple(str(key) for key in CODE_DEFAULTS['logging'])
_HANDLER_FIELDS: Tuple[str, ...] = (
    'type', 'format', 'level', 'stream', 'path', 'max_bytes', 'backup_count', 'encoding',
)
_HANDLER_TYPES: Tuple[str, ...] = ('console', 'file')
_LOG_FORMATS: Tuple[str, ...] = ('text', 'json')
_CONSOLE_STREAMS: Tuple[str, ...] = ('stdout', 'stderr')
_LOG_LEVELS: Tuple[str, ...] = ('CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'NOTSET')
_LOG_LEVEL_ALIASES: Mapping[str, str] = {'WARN': 'WARNING', 'FATAL': 'CRITICAL'}

_TRUE_WORDS = {'1', 'true', 'yes', 'y', 'on'}


# --------------------------------------------------------------------------- YAML
def load_yaml(path: 'os.PathLike[str] | str') -> Dict[str, Any]:
    """读取 YAML 文件并返回顶层映射。"""
    config_path = Path(path)
    try:
        import yaml
    except ImportError:  # pragma: no cover - 依赖缺失时的显式提示
        raise ScnetConfigError(
            '解析 YAML 配置需要 PyYAML，请执行: python -m pip install PyYAML'
        ) from None

    try:
        text = config_path.read_text(encoding='utf-8')
    except OSError as exc:
        raise ScnetConfigError(f'读取配置文件失败: {config_path}: {exc}') from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ScnetConfigError(f'配置文件 YAML 语法错误: {config_path}: {exc}') from exc

    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise ScnetConfigError(f'配置文件顶层必须是映射(mapping): {config_path}')
    return {str(key): value for key, value in data.items()}


def deep_merge(*layers: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """逐层深合并，列表整体替换。"""
    result: Dict[str, Any] = {}
    for layer in layers:
        if not layer:
            continue
        for key, value in layer.items():
            current = result.get(key)
            if isinstance(value, Mapping) and isinstance(current, Mapping):
                result[key] = deep_merge(current, value)
            else:
                result[key] = value
    return result


def _template_for(path: Sequence[str]) -> Any:
    node: Any = CODE_DEFAULTS
    for key in path:
        node = node.get(key) if isinstance(node, Mapping) else None
    return node


def _coerce_like(template: Any, value: Any, source: str) -> Any:
    if isinstance(template, bool):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in _TRUE_WORDS
    if isinstance(template, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ScnetConfigError(f'{source} 需要数值，收到 {value!r}') from None
    if isinstance(template, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ScnetConfigError(f'{source} 需要整数，收到 {value!r}') from None
    if isinstance(template, (list, tuple)):
        if isinstance(value, str):
            items = [item.strip() for item in value.split(',')]
            return [item for item in items if item]
        if isinstance(value, Iterable):
            return [str(item) for item in value]
        raise ScnetConfigError(f'{source} 需要列表，收到 {value!r}')
    return value


def env_layer(env: Mapping[str, str]) -> Dict[str, Any]:
    """把 SCNET_* 环境变量转换为配置层。"""
    layer: Dict[str, Any] = {}
    for env_name, path in ENV_OVERRIDES.items():
        raw = env.get(env_name)
        if raw is None or raw == '':
            continue
        value = _coerce_like(_template_for(path), raw, env_name)
        target = layer
        for key in path[:-1]:
            target = target.setdefault(key, {})
        target[path[-1]] = value
    return layer


# --------------------------------------------------------------- 用户态文件定位
def search_paths(
    *,
    env: Mapping[str, str],
    cwd: Optional[str] = None,
) -> Tuple[Path, ...]:
    """候选用户态配置文件路径（按优先级排列）。"""
    base = Path(cwd) if cwd else Path.cwd()
    home_value = env.get('HOME') or env.get('USERPROFILE')
    home = Path(home_value) if home_value else Path.home()

    candidates = [base / name for name in DEFAULT_CONFIG_NAMES]
    candidates += [home / '.config' / 'scnet' / name for name in DEFAULT_CONFIG_NAMES]
    candidates += [home / f'.{name}' for name in DEFAULT_CONFIG_NAMES]
    return tuple(candidates)


def resolve_config_path(
    config_path: Optional['os.PathLike[str] | str'] = None,
    *,
    env: Mapping[str, str],
    cwd: Optional[str] = None,
    search: bool = True,
) -> Optional[Path]:
    """定位用户态配置文件；显式传入或环境变量指定时文件必须存在。"""
    if config_path is not None:
        path = Path(config_path).expanduser()
        if not path.is_file():
            raise ScnetConfigError(f'指定的配置文件不存在: {path}')
        return path

    from_env = env.get(CONFIG_ENV_VAR)
    if from_env:
        path = Path(from_env).expanduser()
        if not path.is_file():
            raise ScnetConfigError(
                f'环境变量 {CONFIG_ENV_VAR} 指向的配置文件不存在: {path}'
            )
        return path

    if not search:
        return None
    for candidate in search_paths(env=env, cwd=cwd):
        if candidate.is_file():
            return candidate
    return None


def packaged_defaults() -> Dict[str, Any]:
    """读取随包发布的系统态默认配置。"""
    try:
        from importlib.resources import files
    except ImportError:  # pragma: no cover - Python 3.9+ 均有该 API
        return {}

    try:
        resource = files('scnet_sdk').joinpath(PACKAGED_DEFAULTS_NAME)
        if not resource.is_file():
            return {}
        text = resource.read_text(encoding='utf-8')
    except (OSError, ModuleNotFoundError, TypeError):  # pragma: no cover
        return {}

    try:
        import yaml
    except ImportError:  # pragma: no cover
        return {}

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:  # pragma: no cover - 打包资源损坏
        raise ScnetConfigError(f'系统态配置 {PACKAGED_DEFAULTS_NAME} 解析失败: {exc}') from exc
    if not isinstance(data, Mapping):
        return {}
    return {str(key): value for key, value in data.items()}


# ---------------------------------------------------------------------- 配置段
@dataclass(frozen=True)
class Endpoints:
    """认证与授权区域接口地址。"""

    token_url: str = 'https://api.scnet.cn/api/user/v3/tokens'
    center_url: str = 'https://www.scnet.cn/ac/openapi/v2/center'


@dataclass(frozen=True)
class Paths:
    """容器接口路径（拼接在 ai_url 之后）。"""

    resources: str = '/openapi/v2/instance-service/resources'
    task: str = '/openapi/v2/instance-service/task'
    execute_script: str = '/openapi/v2/instance-service/task/actions/execute-script'
    detail: str = '/openapi/v2/instance-service/{container_id}/detail'

    def detail_for(self, container_id: str) -> str:
        return self.detail.format(container_id=container_id)


@dataclass(frozen=True)
class Timeouts:
    """超时配置（秒）。"""

    request: float = 30.0
    wait: float = 1800.0
    poll_interval: float = 5.0


@dataclass(frozen=True)
class StatusSets:
    """容器状态集合（大小写不敏感匹配）。"""

    running: Tuple[str, ...] = ('running',)
    terminal: Tuple[str, ...] = (
        'finished', 'complete', 'completed', 'success', 'succeeded',
        'failed', 'failure', 'error', 'stopped', 'stop', 'canceled', 'cancelled',
    )


@dataclass(frozen=True)
class LogHandlerConfig:
    """单个日志输出目标（log4j 的 appender）。

    - `type=console`：输出到 `stream`（stdout/stderr）
    - `type=file`：输出到 `path`，按 `max_bytes` / `backup_count` 轮转
    - `format`：`text`（人读）或 `json`（机器解析、字段化）
    - `level`：留空则继承全局 `LoggingConfig.level`
    """

    type: str = 'console'
    format: str = 'text'
    level: Optional[str] = None
    stream: str = 'stderr'
    path: Optional[str] = None
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 5
    encoding: str = 'utf-8'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': self.type,
            'format': self.format,
            'level': self.level,
            'stream': self.stream,
            'path': self.path,
            'max_bytes': self.max_bytes,
            'backup_count': self.backup_count,
            'encoding': self.encoding,
        }


@dataclass(frozen=True)
class LoggingConfig:
    """日志系统配置（log4j 风格的 logger 树 + appender + 多语言消息目录）。

    - `level`：`scnet_sdk` 包根级别；`loggers` 可对子 logger 单独降/升级
    - `language`：日志消息语言（`zh_CN` / `en_US`，或 `catalog` 提供的自定义语言）
    - `propagate`：是否向 root logger 传播；保持 True 可与宿主框架（uvicorn /
      FastAPI / Django / Celery 等）的日志配置共存
    - `console` / `file`：常用输出目标的快捷方式
    - `handlers`：完整自定义的 handler 列表，非空时优先于上面两个快捷项
    """

    level: str = 'WARNING'
    language: str = 'zh_CN'
    format: str = 'text'
    propagate: bool = True
    mask_secrets: bool = True
    timestamp_format: str = '%Y-%m-%d %H:%M:%S'
    catalog: Optional[str] = None
    console: bool = False
    console_stream: str = 'stderr'
    file: Optional[str] = None
    file_max_bytes: int = 10 * 1024 * 1024
    file_backup_count: int = 5
    handlers: Tuple[LogHandlerConfig, ...] = ()
    loggers: Mapping[str, str] = field(default_factory=dict)

    def resolved_handlers(self) -> Tuple[LogHandlerConfig, ...]:
        """展开最终使用的 handler 列表。

        快捷方式生成的 handler 不设置自身级别（NOTSET），过滤完全交给 logger 层级，
        这与 log4j「appender 不额外过滤」的语义一致；需要单独过滤时请在
        `handlers` 中显式写 `level`。
        """
        if self.handlers:
            return tuple(self.handlers)
        resolved = []
        if self.console:
            resolved.append(LogHandlerConfig(
                type='console', format=self.format, stream=self.console_stream
            ))
        if self.file:
            resolved.append(LogHandlerConfig(
                type='file',
                format=self.format,
                path=self.file,
                max_bytes=self.file_max_bytes,
                backup_count=self.file_backup_count,
            ))
        return tuple(resolved)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'level': self.level,
            'language': self.language,
            'format': self.format,
            'propagate': self.propagate,
            'mask_secrets': self.mask_secrets,
            'timestamp_format': self.timestamp_format,
            'catalog': self.catalog,
            'console': self.console,
            'console_stream': self.console_stream,
            'file': self.file,
            'file_max_bytes': self.file_max_bytes,
            'file_backup_count': self.file_backup_count,
            'handlers': [item.to_dict() for item in self.handlers],
            'loggers': dict(self.loggers),
        }


def _mask(value: Optional[str]) -> str:
    if not value:
        return '(未设置)'
    text = str(value)
    if len(text) <= 8:
        return '***'
    return f'{text[:4]}***{text[-2:]}'


@dataclass(frozen=True)
class ScnetConfig:
    """SDK 完整配置：系统态（endpoints/paths/timeouts/statuses）+ 用户态（凭证与区域）。"""

    endpoints: Endpoints = field(default_factory=Endpoints)
    paths: Paths = field(default_factory=Paths)
    timeouts: Timeouts = field(default_factory=Timeouts)
    statuses: StatusSets = field(default_factory=StatusSets)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # 用户态
    cluster_id: Optional[str] = None
    ai_url: Optional[str] = None
    user: Optional[str] = None
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    token: Optional[str] = None
    signing_compact: bool = True

    # 诊断信息：加载来源
    sources: Tuple[str, ...] = ()

    # ------------------------------------------------------------------ 构造
    @classmethod
    def load(
        cls,
        config_path: Optional['os.PathLike[str] | str'] = None,
        *,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[str] = None,
        search_user_config: bool = True,
        use_environment: bool = True,
        **overrides: Any,
    ) -> 'ScnetConfig':
        """按「内置默认值 -> 系统态 YAML -> 用户态 YAML -> 环境变量 -> 传参」合并加载。"""
        env_map: Dict[str, str] = (
            {str(k): str(v) for k, v in os.environ.items()} if env is None else dict(env)
        )

        layers: list = [CODE_DEFAULTS, packaged_defaults()]
        sources: list = ['代码内置默认值', f'系统态 {PACKAGED_DEFAULTS_NAME}']

        if search_user_config or config_path is not None:
            user_path = resolve_config_path(
                config_path, env=env_map, cwd=cwd, search=search_user_config
            )
            if user_path is not None:
                layers.append(load_yaml(user_path))
                sources.append(f'用户态 {user_path}')

        if use_environment:
            from_env = env_layer(env_map)
            if from_env:
                layers.append(from_env)
                sources.append(f'环境变量 {ENV_PREFIX}*')

        if overrides:
            layers.append({key: value for key, value in overrides.items() if value is not None})
            sources.append('代码传参')

        merged = deep_merge(*layers)
        return cls.from_mapping(merged, sources=tuple(sources))

    @classmethod
    def from_mapping(
        cls,
        mapping: Mapping[str, Any],
        *,
        sources: Sequence[str] = (),
    ) -> 'ScnetConfig':
        """由已合并的映射构建配置对象，并做键名与取值校验。"""
        mapping = dict(mapping or {})

        allowed = set(_SECTION_FIELDS) | set(USER_FIELDS) | {'logging'}
        unknown = sorted(set(mapping) - allowed)
        if unknown:
            raise ScnetConfigError(
                f'未知配置项 {unknown}；可用项: {sorted(allowed)}'
            )

        sections: Dict[str, Dict[str, Any]] = {}
        for section, fields in _SECTION_FIELDS.items():
            raw = mapping.get(section) or {}
            if not isinstance(raw, Mapping):
                raise ScnetConfigError(f'配置段 {section} 必须是映射(mapping)')
            extra = sorted(set(raw) - set(fields))
            if extra:
                raise ScnetConfigError(
                    f'配置段 {section} 存在未知键 {extra}；可用键: {list(fields)}'
                )
            sections[section] = dict(raw)

        endpoints = Endpoints(
            token_url=_require_text(sections['endpoints'], 'token_url', 'endpoints'),
            center_url=_require_text(sections['endpoints'], 'center_url', 'endpoints'),
        )
        paths = Paths(
            resources=_require_text(sections['paths'], 'resources', 'paths'),
            task=_require_text(sections['paths'], 'task', 'paths'),
            execute_script=_require_text(sections['paths'], 'execute_script', 'paths'),
            detail=_require_text(sections['paths'], 'detail', 'paths'),
        )
        if '{container_id}' not in paths.detail:
            raise ScnetConfigError(
                f"paths.detail 必须包含 '{{container_id}}' 占位符，当前: {paths.detail}"
            )

        timeouts = Timeouts(
            request=_positive_float(sections['timeouts'], 'request', 30.0),
            wait=_positive_float(sections['timeouts'], 'wait', 1800.0),
            poll_interval=_positive_float(sections['timeouts'], 'poll_interval', 5.0),
        )
        statuses = StatusSets(
            running=_status_tuple(sections['statuses'], 'running', required=True),
            terminal=_status_tuple(sections['statuses'], 'terminal', required=False),
        )
        logging_config = logging_config_from_mapping(mapping.get('logging') or {})

        return cls(
            endpoints=endpoints,
            paths=paths,
            timeouts=timeouts,
            statuses=statuses,
            logging=logging_config,
            cluster_id=_optional_text(mapping.get('cluster_id')),
            ai_url=_optional_text(mapping.get('ai_url')),
            user=_optional_text(mapping.get('user')),
            access_key=_optional_text(mapping.get('access_key')),
            secret_key=_optional_text(mapping.get('secret_key')),
            token=_optional_text(mapping.get('token')),
            signing_compact=bool(
                _coerce_like(True, mapping.get('signing_compact', True), 'signing_compact')
            ),
            sources=tuple(sources),
        )

    # ------------------------------------------------------------------ 覆盖
    def with_overrides(
        self,
        *,
        token: Optional[str] = None,
        ai_url: Optional[str] = None,
        cluster_id: Optional[str] = None,
        user: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        request_timeout: Optional[float] = None,
        wait_timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
        running_statuses: Optional[Sequence[str]] = None,
        terminal_statuses: Optional[Sequence[str]] = None,
        log_level: Optional[str] = None,
        log_language: Optional[str] = None,
        log_format: Optional[str] = None,
    ) -> 'ScnetConfig':
        """返回覆盖了指定字段的新配置（None 表示保持原值）。"""
        changes: Dict[str, Any] = {}
        if token is not None:
            changes['token'] = token
        if ai_url is not None:
            changes['ai_url'] = ai_url
        if cluster_id is not None:
            changes['cluster_id'] = cluster_id
        if user is not None:
            changes['user'] = user
        if access_key is not None:
            changes['access_key'] = access_key
        if secret_key is not None:
            changes['secret_key'] = secret_key

        config = replace(self, **changes) if changes else self

        timeout_changes: Dict[str, float] = {}
        if request_timeout is not None:
            timeout_changes['request'] = float(request_timeout)
        if wait_timeout is not None:
            timeout_changes['wait'] = float(wait_timeout)
        if poll_interval is not None:
            timeout_changes['poll_interval'] = float(poll_interval)
        if timeout_changes:
            config = replace(config, timeouts=replace(config.timeouts, **timeout_changes))

        status_changes: Dict[str, Tuple[str, ...]] = {}
        if running_statuses is not None:
            status_changes['running'] = tuple(running_statuses)
        if terminal_statuses is not None:
            status_changes['terminal'] = tuple(terminal_statuses)
        if status_changes:
            config = replace(config, statuses=replace(config.statuses, **status_changes))

        log_changes: Dict[str, Any] = {}
        if log_level is not None:
            log_changes['level'] = _validate_log_level(log_level, 'log_level')
        if log_language is not None:
            log_changes['language'] = str(log_language)
        if log_format is not None:
            log_changes['format'] = _validate_choice('log_format', log_format, _LOG_FORMATS)
        if log_changes:
            config = replace(config, logging=replace(config.logging, **log_changes))

        return config

    # ------------------------------------------------------------------ 输出
    def to_dict(self) -> Dict[str, Any]:
        """转为嵌套字典（含明文凭证，谨慎输出）。"""
        return {
            'endpoints': {
                'token_url': self.endpoints.token_url,
                'center_url': self.endpoints.center_url,
            },
            'paths': {
                'resources': self.paths.resources,
                'task': self.paths.task,
                'execute_script': self.paths.execute_script,
                'detail': self.paths.detail,
            },
            'timeouts': {
                'request': self.timeouts.request,
                'wait': self.timeouts.wait,
                'poll_interval': self.timeouts.poll_interval,
            },
            'statuses': {
                'running': list(self.statuses.running),
                'terminal': list(self.statuses.terminal),
            },
            'logging': self.logging.to_dict(),
            'cluster_id': self.cluster_id,
            'ai_url': self.ai_url,
            'user': self.user,
            'access_key': self.access_key,
            'secret_key': self.secret_key,
            'token': self.token,
            'signing_compact': self.signing_compact,
        }

    def describe(self) -> str:
        """人类可读的配置摘要（凭证已脱敏）。"""
        lines = [
            'SCNet SDK 配置',
            f'  加载来源: {" -> ".join(self.sources) if self.sources else "(未记录)"}',
            f'  认证地址: token={self.endpoints.token_url}',
            f'            center={self.endpoints.center_url}',
            f'  容器地址: {self.ai_url or "(未设置，首次调用时自动解析)"}',
            f'  区域/用户: {self.cluster_id or "(未指定)"} / {self.user or "(未设置)"}',
            f'  凭证: AK={_mask(self.access_key)} SK={_mask(self.secret_key)} token={_mask(self.token)}',
            f'  超时: request={self.timeouts.request}s wait={self.timeouts.wait}s '
            f'poll={self.timeouts.poll_interval}s',
            f'  路径: task={self.paths.task}',
            f'        detail={self.paths.detail}',
            f'  运行态: {list(self.statuses.running)}',
            f'  终态: {list(self.statuses.terminal)}',
            f'  日志: 级别={self.logging.level} 语言={self.logging.language} '
            f'格式={self.logging.format} 传播={self.logging.propagate}',
            f'        输出={_describe_handlers(self.logging)}',
        ]
        return '\n'.join(lines)

    def __str__(self) -> str:
        return self.describe()


# ------------------------------------------------------------------ 取值辅助
def _require_text(section: Mapping[str, Any], key: str, section_name: str) -> str:
    value = section.get(key)
    text = _optional_text(value)
    if not text:
        raise ScnetConfigError(f'配置项 {section_name}.{key} 不能为空')
    return text


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _positive_float(section: Mapping[str, Any], key: str, fallback: float) -> float:
    value = section.get(key, fallback)
    number = _coerce_like(float(fallback), value, key)
    if number <= 0:
        raise ScnetConfigError(f'配置项 timeouts.{key} 必须大于 0，收到 {number}')
    return float(number)


def _status_tuple(section: Mapping[str, Any], key: str, *, required: bool) -> Tuple[str, ...]:
    value = section.get(key)
    if value is None:
        value = _template_for(('statuses', key))
    values = _coerce_like(['x'], value, f'statuses.{key}')
    cleaned = tuple(str(item).strip() for item in values if str(item).strip())
    if required and not cleaned:
        raise ScnetConfigError(f'配置项 statuses.{key} 不能为空')
    return cleaned


# --------------------------------------------------------------- 日志配置构建
def _validate_choice(name: str, value: Any, choices: Sequence[str]) -> str:
    text = str(value).strip()
    if text.lower() not in {item.lower() for item in choices}:
        raise ScnetConfigError(f'配置项 {name}={value!r} 非法；可选: {list(choices)}')
    return text


def _validate_log_level(value: Any, source: str) -> str:
    text = str(value).strip().upper()
    if not text:
        raise ScnetConfigError(f'配置项 {source} 不能为空')
    text = _LOG_LEVEL_ALIASES.get(text, text)
    if text not in _LOG_LEVELS:
        raise ScnetConfigError(
            f'配置项 {source} 不是合法的日志级别: {value!r}；可选: {list(_LOG_LEVELS)}'
        )
    return text


def _int_value(
    section: Mapping[str, Any], key: str, fallback: int, source: str, *, minimum: int = 0
) -> int:
    value = section.get(key, fallback)
    if value is None:
        value = fallback
    number = int(_coerce_like(int(fallback), value, f'{source}.{key}'))
    if number < minimum:
        raise ScnetConfigError(f'配置项 {source}.{key} 不能小于 {minimum}，收到 {number}')
    return number


def _build_handler_config(raw: Any, index: int) -> LogHandlerConfig:
    source = f'logging.handlers[{index}]'
    if not isinstance(raw, Mapping):
        raise ScnetConfigError(f'{source} 必须是映射(mapping)')

    extra = sorted(set(raw) - set(_HANDLER_FIELDS))
    if extra:
        raise ScnetConfigError(
            f'{source} 存在未知键 {extra}；可用键: {list(_HANDLER_FIELDS)}'
        )

    handler_type = _validate_choice(f'{source}.type', raw.get('type', 'console'), _HANDLER_TYPES).lower()
    path = _optional_text(raw.get('path'))
    if handler_type == 'file' and not path:
        raise ScnetConfigError(f'{source} 为 file 类型时必须提供 path')

    level = raw.get('level')
    return LogHandlerConfig(
        type=handler_type,
        format=_validate_choice(f'{source}.format', raw.get('format', 'text'), _LOG_FORMATS).lower(),
        level=_validate_log_level(level, f'{source}.level') if level else None,
        stream=_validate_choice(
            f'{source}.stream', raw.get('stream', 'stderr'), _CONSOLE_STREAMS
        ).lower(),
        path=path,
        max_bytes=_int_value(raw, 'max_bytes', 10 * 1024 * 1024, source, minimum=0),
        backup_count=_int_value(raw, 'backup_count', 5, source, minimum=0),
        encoding=_optional_text(raw.get('encoding')) or 'utf-8',
    )


def logging_config_from_mapping(mapping: Mapping[str, Any]) -> LoggingConfig:
    """由映射构建日志配置。

    YAML 的 `logging:` 段与外部字典两种入口共用，因此单独导出。
    """
    mapping = dict(mapping or {})
    extra = sorted(set(mapping) - set(_LOGGING_FIELDS))
    if extra:
        raise ScnetConfigError(
            f'配置段 logging 存在未知键 {extra}；可用键: {list(_LOGGING_FIELDS)}'
        )

    raw_handlers = mapping.get('handlers') or ()
    if isinstance(raw_handlers, (str, bytes, Mapping)):
        raise ScnetConfigError('配置项 logging.handlers 必须是列表')
    handlers = tuple(
        _build_handler_config(item, index) for index, item in enumerate(raw_handlers)
    )

    raw_loggers = mapping.get('loggers') or {}
    if not isinstance(raw_loggers, Mapping):
        raise ScnetConfigError('配置项 logging.loggers 必须是映射(mapping)：{logger 名称: 级别}')
    loggers = {
        str(name): _validate_log_level(level, f'logging.loggers.{name}')
        for name, level in raw_loggers.items()
        if level is not None
    }

    return LoggingConfig(
        level=_validate_log_level(mapping.get('level', 'WARNING'), 'logging.level'),
        language=_optional_text(mapping.get('language')) or 'zh_CN',
        format=_validate_choice(
            'logging.format', mapping.get('format', 'text'), _LOG_FORMATS
        ).lower(),
        propagate=bool(_coerce_like(True, mapping.get('propagate', True), 'logging.propagate')),
        mask_secrets=bool(
            _coerce_like(True, mapping.get('mask_secrets', True), 'logging.mask_secrets')
        ),
        timestamp_format=_optional_text(mapping.get('timestamp_format')) or '%Y-%m-%d %H:%M:%S',
        catalog=_optional_text(mapping.get('catalog')),
        console=bool(_coerce_like(False, mapping.get('console', False), 'logging.console')),
        console_stream=_validate_choice(
            'logging.console_stream', mapping.get('console_stream', 'stderr'), _CONSOLE_STREAMS
        ).lower(),
        file=_optional_text(mapping.get('file')),
        file_max_bytes=_int_value(mapping, 'file_max_bytes', 10 * 1024 * 1024, 'logging'),
        file_backup_count=_int_value(mapping, 'file_backup_count', 5, 'logging'),
        handlers=handlers,
        loggers=loggers,
    )


def _describe_handlers(config: LoggingConfig) -> str:
    handlers = config.resolved_handlers()
    if not handlers:
        return '(未配置输出目标，沿用宿主框架日志配置)'
    return ', '.join(
        f'{item.type}({item.path or item.stream}/{item.format}/{item.level or "inherit"})'
        for item in handlers
    )
