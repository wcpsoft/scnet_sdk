"""log4j 风格日志系统：分级 logger 树 + 可插拔 handler/formatter + 多语言消息目录。

设计目标
--------
1. **log4j 式**：`scnet_sdk` 及其子 logger 构成层级（`scnet_sdk.client`、
   `scnet_sdk.auth` …），级别可逐级覆盖；handler 相当于 appender，可同时挂
   控制台与轮转文件；formatter 支持 `text` / `json` 两种。
2. **任意框架可集成**：默认不添加任何输出 handler，只向 root logger 传播
   （`propagate=True`），因此 uvicorn / FastAPI / Django / Celery 等宿主框架
   的日志配置能直接接管；需要独立输出时调用 :func:`configure_logging`，或用
   :func:`logging_config_dict` 生成 `logging.config.dictConfig` 片段。
3. **多语言**：日志消息不是硬编码字符串，而是「事件名 + 字段」，由
   `scnet_sdk/locales/<语言>.yaml` 目录渲染。切换 `logging.language` 即可让
   所有日志输出中文/英文；`catalog` 可指向自定义目录扩展语言。结构化输出
   （json）额外保留 `event` 与 `fields`，与语言无关，便于日志采集与告警。
4. **不泄密**：`mask_secrets=True` 时按 key（token/access_key/secret_key/
   signature/cookie/...）与 JWT 形态自动打码。

最简用法::

    import scnet_sdk

    scnet_sdk.configure_logging()                   # 用配置里的日志设置初始化
    scnet_sdk.configure_logging(level='INFO', console=True, language='zh_CN')
    logger = scnet_sdk.get_logger('client')

与宿主框架共存::

    # 方案 A：让宿主框架的 root 配置捕获（推荐，什么都不用做）
    # 方案 B：把下面的片段并进自己的 dictConfig
    import logging.config, scnet_sdk
    logging.config.dictConfig(scnet_sdk.logging_config_dict())
"""
from __future__ import annotations

import json
import logging as pylogging
import logging.handlers
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence, Tuple, Union

from .config import LogHandlerConfig, LoggingConfig, ScnetConfig, logging_config_from_mapping
from .errors import ScnetConfigError

ROOT_LOGGER_NAME = 'scnet_sdk'
DEFAULT_LANGUAGE = 'en_US'
LOCALES_DIRNAME = 'locales'

# 级别常量（等价 stdlib logging 数值），便于内部模块只依赖本模块
CRITICAL = pylogging.CRITICAL
ERROR = pylogging.ERROR
WARNING = pylogging.WARNING
INFO = pylogging.INFO
DEBUG = pylogging.DEBUG
NOTSET = pylogging.NOTSET

_SENSITIVE_KEYS = {
    'token', 'access_key', 'accesskey', 'ak', 'secret_key', 'secretkey', 'sk',
    'password', 'passwd', 'signature', 'authorization', 'cookie', 'session', 'credential',
}
_JWT_PATTERN = re.compile(r'\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.?[A-Za-z0-9_\-]*')
_MASKED = '***'

_context: ContextVar[Dict[str, Any]] = ContextVar('scnet_sdk_log_context', default={})

_STATE: Dict[str, Any] = {
    'configured': False,
    'language': 'zh_CN',
    'mask_secrets': True,
    'catalogs': {},
    'catalog_source': None,
    'managed_loggers': (),
}

# 库的最佳实践：默认挂 NullHandler，既不输出也不阻止向 root 传播
pylogging.getLogger(ROOT_LOGGER_NAME).addHandler(pylogging.NullHandler())


# ------------------------------------------------------------------ 语言目录
def _locales_root() -> Optional[Path]:
    try:
        from importlib.resources import files
    except ImportError:  # pragma: no cover
        return None
    try:
        resource = files('scnet_sdk').joinpath(LOCALES_DIRNAME)
        if not resource.is_dir():
            return None
        return Path(str(resource))
    except (OSError, ModuleNotFoundError, TypeError):  # pragma: no cover
        return None


def _read_catalog_file(path: Path) -> Dict[str, str]:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        raise ScnetConfigError(
            '解析语言包需要 PyYAML，请执行: python -m pip install PyYAML'
        ) from None
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
    except OSError as exc:
        raise ScnetConfigError(f'读取语言包失败: {path}: {exc}') from exc
    except yaml.YAMLError as exc:
        raise ScnetConfigError(f'语言包 YAML 语法错误: {path}: {exc}') from exc

    if not isinstance(data, Mapping):
        raise ScnetConfigError(f'语言包顶层必须是映射(mapping): {path}')
    events = data.get('events')
    if not isinstance(events, Mapping):
        raise ScnetConfigError(f"语言包缺少 'events' 段: {path}")
    return {str(key): str(value) for key, value in events.items()}


def available_languages() -> Tuple[str, ...]:
    """返回内置 + 自定义目录中可用的语言列表。"""
    languages = []
    root = _locales_root()
    if root is not None:
        languages += [item.stem for item in sorted(root.glob('*.yaml'))]

    source = _STATE.get('catalog_source')
    if source:
        path = Path(source).expanduser()
        if path.is_dir():
            languages += [item.stem for item in sorted(path.glob('*.yaml'))]
        elif path.is_file():
            languages.append(path.stem)

    return tuple(dict.fromkeys(languages))


def load_catalog(language: str, *, catalog: Optional[str] = None) -> Dict[str, str]:
    """加载指定语言的消息目录；自定义 `catalog` 覆盖内置同名 key。"""
    events: Dict[str, str] = {}
    root = _locales_root()
    if root is not None:
        packaged = root / f'{language}.yaml'
        if packaged.is_file():
            events.update(_read_catalog_file(packaged))

    if catalog:
        path = Path(catalog).expanduser()
        candidates = [path] if path.is_file() else [path / f'{language}.yaml']
        for candidate in candidates:
            if candidate.is_file():
                events.update(_read_catalog_file(candidate))
                break
    return events


def _catalog_for(language: Optional[str] = None) -> Dict[str, str]:
    language = language or current_language()
    cache: Dict[str, Dict[str, str]] = _STATE['catalogs']
    if language not in cache:
        cache[language] = load_catalog(language, catalog=_STATE.get('catalog_source'))
    return cache[language]


def current_language() -> str:
    """当前日志消息语言。"""
    return str(_STATE.get('language') or 'zh_CN')


def set_language(language: str) -> str:
    """运行期切换日志消息语言，返回切换后的语言。"""
    text = str(language).strip()
    if not text:
        raise ScnetConfigError('日志语言不能为空')
    _STATE['language'] = text
    return text


def render_event(event: str, fields: Mapping[str, Any], language: Optional[str] = None) -> str:
    """按当前语言渲染日志消息；缺失占位符时追加原始字段，保证不丢信息。"""
    catalog = _catalog_for(language)
    template = catalog.get(event)
    if template is None:
        template = _catalog_for(DEFAULT_LANGUAGE).get(event)
    if template is None:
        template = event
    try:
        return template.format(**fields)
    except (KeyError, IndexError, ValueError):
        return f'{template} {json.dumps(dict(fields), ensure_ascii=False, default=str)}'


# ------------------------------------------------------------------ 脱敏
def mask_fields(fields: Mapping[str, Any]) -> Dict[str, Any]:
    """按 key 名对敏感字段打码（递归到嵌套映射与序列）。

    日志一律整体替换为 `***`（不做部分保留），避免任何凭证片段进入日志系统。
    """
    masked: Dict[str, Any] = {}
    for key, value in fields.items():
        if str(key).lower() in _SENSITIVE_KEYS:
            masked[key] = _MASKED
        elif isinstance(value, Mapping):
            masked[key] = mask_fields(value)
        elif isinstance(value, (list, tuple)):
            masked[key] = [
                mask_fields(item) if isinstance(item, Mapping) else _mask_text(str(item))
                for item in value
            ]
        elif isinstance(value, str):
            masked[key] = _mask_text(value)
        else:
            masked[key] = value
    return masked


def _mask_text(text: str) -> str:
    """把字符串里出现的 JWT 形态凭证整体打码。"""
    return _JWT_PATTERN.sub(_MASKED, text)


# ------------------------------------------------------------------ 上下文
def current_context() -> Mapping[str, Any]:
    """当前日志上下文字段（`log_context` / `bind_context` 绑定）。"""
    return dict(_context.get() or {})


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """在作用域内绑定日志上下文字段（同步/异步、contextvars 均生效）。

    典型用途：把 `request_id` / `container_id` / 租户信息注入该作用域内的所有日志。
    """
    merged = {**(_context.get() or {}), **fields}
    token = _context.set(merged)
    try:
        yield
    finally:
        _context.reset(token)


def bind_context(**fields: Any) -> None:
    """绑定上下文字段直到当前 context 结束（不自动清理）。"""
    _context.set({**(_context.get() or {}), **fields})


def clear_context() -> None:
    """清空当前上下文字段。"""
    _context.set({})


# ------------------------------------------------------------------ Formatter
class TextFormatter(pylogging.Formatter):
    """人类可读格式：`时间 级别 logger | 消息 | k=v`。"""

    def __init__(
        self,
        *,
        timestamp_format: str = '%Y-%m-%d %H:%M:%S',
        mask_secrets: bool = True,
    ):
        super().__init__()
        self.timestamp_format = timestamp_format
        self.mask_secrets = mask_secrets

    def format(self, record: pylogging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime(self.timestamp_format)
        parts = [timestamp, f'{record.levelname:<8}', record.name, '|', record.getMessage()]

        fields = dict(getattr(record, 'scnet_fields', None) or {})
        fields.update({k: v for k, v in current_context().items() if k not in fields})
        if fields:
            parts.append('| ' + ' '.join(f'{key}={_stringify(value)}' for key, value in fields.items()))

        text = ' '.join(parts)
        if record.exc_info:
            text += '\n' + self.formatException(record.exc_info)
        return _mask_text(text) if self.mask_secrets else text


class JsonFormatter(pylogging.Formatter):
    """结构化格式：字段化输出，`event` + `fields` 与语言无关。"""

    def __init__(self, *, mask_secrets: bool = True):
        super().__init__()
        self.mask_secrets = mask_secrets

    def format(self, record: pylogging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            'ts': datetime.fromtimestamp(record.created).isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'logger': record.name,
            'event': getattr(record, 'scnet_event', None),
            'message': record.getMessage(),
            'language': getattr(record, 'scnet_language', None),
        }

        fields = getattr(record, 'scnet_fields', None)
        if fields:
            payload['fields'] = fields
        context = current_context()
        if context:
            payload['context'] = context
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)

        payload = {key: value for key, value in payload.items() if value is not None}
        if self.mask_secrets:
            payload = mask_fields(payload)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def build_formatter(fmt: str, config: LoggingConfig) -> pylogging.Formatter:
    """按名称构建 formatter（`text` / `json`）。"""
    name = str(fmt or config.format).lower()
    if name == 'json':
        return JsonFormatter(mask_secrets=config.mask_secrets)
    if name == 'text':
        return TextFormatter(
            timestamp_format=config.timestamp_format, mask_secrets=config.mask_secrets
        )
    raise ScnetConfigError(f'不支持的日志格式: {fmt!r}；可选: text / json')


# ------------------------------------------------------------------ 记录入口
def get_logger(name: Optional[str] = None) -> pylogging.Logger:
    """获取 SDK 命名空间下的 logger（`scnet_sdk` 或其子 logger）。"""
    if not name:
        return pylogging.getLogger(ROOT_LOGGER_NAME)
    if str(name) == ROOT_LOGGER_NAME or str(name).startswith(f'{ROOT_LOGGER_NAME}.'):
        return pylogging.getLogger(str(name))
    return pylogging.getLogger(f'{ROOT_LOGGER_NAME}.{name}')


def log_event(
    logger: pylogging.Logger,
    level: int,
    event: str,
    /,
    *,
    exc_info: Any = None,
    **fields: Any,
) -> None:
    """记录一条「事件 + 字段」日志，按当前语言渲染消息。

    前三个参数是位置参数，因此 `level` / `event` / `logger` 也可以安全地作为
    字段名传入（例如 `log_event(log, INFO, 'evt', level='INFO')`）。
    字段 `log_language` 为保留字段，用于单条日志切换输出语言（不会输出到字段里）；
    普通字段名 `language` 不受影响，可作为业务字段正常使用。
    """
    if not logger.isEnabledFor(level):
        return

    payload = {key: value for key, value in fields.items() if value is not None}
    language = payload.pop('log_language', None) or current_context().get('log_language')
    language = str(language) if language else current_language()

    safe_fields = mask_fields(payload) if _STATE.get('mask_secrets', True) else payload
    message = render_event(event, safe_fields, language)

    logger.log(
        level,
        message,
        extra={
            'scnet_event': event,
            'scnet_fields': safe_fields,
            'scnet_language': language,
        },
        exc_info=exc_info,
    )


# ------------------------------------------------------------------ 配置应用
def _remove_managed_handlers(logger: pylogging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, '_scnet_managed', False):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # pragma: no cover - 关闭失败不影响后续
                pass


def _build_handler(config: LogHandlerConfig, logging_config: LoggingConfig) -> pylogging.Handler:
    if config.type == 'file':
        if not config.path:
            raise ScnetConfigError('file handler 必须提供 path')
        path = Path(config.path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler: pylogging.Handler = pylogging.handlers.RotatingFileHandler(
            path,
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding=config.encoding,
        )
    else:
        stream = sys.stdout if config.stream == 'stdout' else sys.stderr
        handler = pylogging.StreamHandler(stream)

    handler.setFormatter(build_formatter(config.format, logging_config))
    # handler 默认不做级别过滤（NOTSET），过滤交给 logger 层级；显式配置 level 时生效
    handler.setLevel(pylogging.getLevelName(config.level) if config.level else pylogging.NOTSET)
    handler._scnet_managed = True  # type: ignore[attr-defined]
    return handler


def resolve_logging_config(
    config: Union[None, ScnetConfig, LoggingConfig, Mapping[str, Any]] = None,
    overrides: Optional[Mapping[str, Any]] = None,
) -> LoggingConfig:
    """把各种入参统一成 :class:`LoggingConfig`。"""
    if config is None:
        logging_config = ScnetConfig.load().logging
    elif isinstance(config, ScnetConfig):
        logging_config = config.logging
    elif isinstance(config, LoggingConfig):
        logging_config = config
    elif isinstance(config, Mapping):
        logging_config = logging_config_from_mapping(config)
    else:
        raise ScnetConfigError(
            f'configure_logging 不支持的类型: {type(config).__name__}'
        )

    if overrides:
        changes: Dict[str, Any] = {}
        for key, value in overrides.items():
            if value is None:
                continue
            if key == 'level':
                changes['level'] = str(value).upper()
            elif key in ('language', 'format', 'catalog', 'timestamp_format', 'console_stream'):
                changes[key] = str(value)
            elif key in ('propagate', 'mask_secrets', 'console'):
                changes[key] = bool(value)
            else:
                raise ScnetConfigError(f'configure_logging 不支持覆盖 {key!r}')
        logging_config = replace(logging_config, **changes)
    return logging_config


def configure_logging(
    config: Union[None, ScnetConfig, LoggingConfig, Mapping[str, Any]] = None,
    *,
    force: bool = False,
    **overrides: Any,
) -> LoggingConfig:
    """初始化日志系统（幂等）。

    参数
    ----
    config:
        `ScnetConfig` / `LoggingConfig` / 日志配置段的映射；留空时用
        `ScnetConfig.load().logging`（即系统态 + 用户态 + 环境变量）。
    force:
        为 True 时先移除本库此前挂载的 handler 再重建（用于运行期改配置）。
    overrides:
        `level` / `language` / `format` / `console` / `console_stream` /
        `propagate` / `mask_secrets` / `catalog` 单项覆盖。

    说明：`logging.handlers` 为空时，显式调用本函数会默认挂一个控制台 handler，
    否则「调用 configure_logging 却没有输出」会很困惑；不调用本函数时，本库
    保持静默并沿用宿主框架的日志配置。
    """
    logging_config = resolve_logging_config(config, overrides)

    _STATE['language'] = logging_config.language
    _STATE['mask_secrets'] = logging_config.mask_secrets
    _STATE['catalog_source'] = logging_config.catalog
    _STATE['catalogs'] = {}

    root = pylogging.getLogger(ROOT_LOGGER_NAME)
    if force or not _STATE['configured']:
        _remove_managed_handlers(root)

        handlers = logging_config.resolved_handlers()
        if not handlers:
            handlers = (
                LogHandlerConfig(
                    type='console',
                    format=logging_config.format,
                    stream=logging_config.console_stream,
                ),
            )
        for handler_config in handlers:
            root.addHandler(_build_handler(handler_config, logging_config))

        for name in _STATE.get('managed_loggers', ()):
            pylogging.getLogger(name).setLevel(pylogging.NOTSET)

        managed = []
        for name, level in logging_config.loggers.items():
            logger = get_logger(name)
            logger.setLevel(pylogging.getLevelName(level) if isinstance(level, str) else level)
            managed.append(logger.name)
        _STATE['managed_loggers'] = tuple(managed)
        _STATE['configured'] = True

    root.setLevel(pylogging.getLevelName(logging_config.level))
    root.propagate = logging_config.propagate

    if not load_catalog(logging_config.language, catalog=logging_config.catalog):
        log_event(
            root,
            pylogging.WARNING,
            'logging.language.missing',
            requested=logging_config.language,
            fallback=DEFAULT_LANGUAGE,
        )

    log_event(
        root,
        pylogging.DEBUG,
        'logging.configured',
        language=logging_config.language,
        level=logging_config.level,
        handlers=[item.type for item in logging_config.resolved_handlers()] or ['console(default)'],
    )
    return logging_config


def logging_config_dict(
    config: Union[None, ScnetConfig, LoggingConfig, Mapping[str, Any]] = None,
    *,
    force: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """生成可直接交给 `logging.config.dictConfig` 的配置片段。

    便于在 Django / FastAPI / Celery 等已统一管理日志的项目里，把本库日志
    并入既有 handler 体系（同一格式、同一落盘策略）。
    """
    logging_config = resolve_logging_config(config, overrides)
    handlers = logging_config.resolved_handlers()
    if not handlers:
        handlers = (
            LogHandlerConfig(
                type='console',
                format=logging_config.format,
                stream=logging_config.console_stream,
            ),
        )

    formatters: Dict[str, Any] = {}
    handler_dicts: Dict[str, Any] = {}
    handler_names = []
    for index, handler_config in enumerate(handlers):
        handler_name = f'scnet_{handler_config.type}_{index}'
        formatter_name = f'scnet_{handler_config.format}'
        handler_names.append(handler_name)

        if handler_config.format == 'json':
            formatters[formatter_name] = {
                '()': 'scnet_sdk.logging.JsonFormatter',
                'mask_secrets': logging_config.mask_secrets,
            }
        else:
            formatters[formatter_name] = {
                '()': 'scnet_sdk.logging.TextFormatter',
                'timestamp_format': logging_config.timestamp_format,
                'mask_secrets': logging_config.mask_secrets,
            }

        if handler_config.type == 'file':
            entry: Dict[str, Any] = {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': handler_config.path,
                'maxBytes': handler_config.max_bytes,
                'backupCount': handler_config.backup_count,
                'encoding': handler_config.encoding,
                'formatter': formatter_name,
            }
        else:
            entry = {
                'class': 'logging.StreamHandler',
                'stream': f'ext://sys.{handler_config.stream}',
                'formatter': formatter_name,
            }
        if handler_config.level:
            entry['level'] = handler_config.level
        handler_dicts[handler_name] = entry

    loggers: Dict[str, Any] = {
        ROOT_LOGGER_NAME: {
            'level': logging_config.level,
            'handlers': handler_names,
            'propagate': logging_config.propagate,
        }
    }
    for name, level in logging_config.loggers.items():
        loggers[get_logger(name).name] = {'level': level, 'handlers': [], 'propagate': True}

    return {
        'version': 1,
        'disable_existing_loggers': bool(force),
        'formatters': formatters,
        'handlers': handler_dicts,
        'loggers': loggers,
    }


def is_configured() -> bool:
    """本库的 handler 是否已由 :func:`configure_logging` 挂载。"""
    return bool(_STATE.get('configured'))


def reset_logging() -> None:
    """移除本库挂载的 handler 并清空语言/上下文状态（主要供测试使用）。"""
    root = pylogging.getLogger(ROOT_LOGGER_NAME)
    _remove_managed_handlers(root)
    for name in _STATE.get('managed_loggers', ()):
        pylogging.getLogger(name).setLevel(pylogging.NOTSET)
    _STATE.update({
        'configured': False,
        'language': 'zh_CN',
        'mask_secrets': True,
        'catalogs': {},
        'catalog_source': None,
        'managed_loggers': (),
    })
    clear_context()
