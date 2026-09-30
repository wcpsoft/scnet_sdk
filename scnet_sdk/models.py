"""SCNet 容器接口的请求与响应模型。

字段名与取值严格对齐 api/scnet 文档：
- 创建容器实例：`03-create-container.md`
- 实例详情（状态）：`05-container-status.md`
- 节点资源限额：`02-resources.md`
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .errors import ScnetValidationError

# 官方文档标注的枚举取值
ACCELERATOR_TYPES = ('mlu', 'dcu', 'gpu', 'cpu')
TASK_TYPES = ('ssh', 'jupyter', 'codeserver', 'rstudio')
PROTOCOL_TYPES = ('SSH', 'HTTP')
MOUNT_TYPES = ('data', 'path')
SCRIPT_ACTION_SCOPES = ('all', 'header')

# 官方开放 API 文档未给出 status 的完整英文枚举，示例中只出现过 `Waiting`；
# 控制台帮助文档给出的 6 种中文状态为：等待 / 部署 / 运行 / 完成 / 失败 / 停止。
# 下面两个集合用于 is_running / is_terminal 判断，比较时忽略大小写，
# 若实际返回值与默认值不同，请在调用时显式传入 running_statuses / failed_statuses。
DEFAULT_RUNNING_STATUSES: Tuple[str, ...] = ('running',)
DEFAULT_TERMINAL_STATUSES: Tuple[str, ...] = (
    'finished', 'complete', 'completed', 'success', 'succeeded',
    'failed', 'failure', 'error', 'stopped', 'stop', 'canceled', 'cancelled',
)


def status_matches(status: Optional[str], candidates: Iterable[str]) -> bool:
    """大小写不敏感地判断状态是否命中候选集合。"""
    if not status:
        return False
    return str(status).strip().lower() in {str(item).strip().lower() for item in candidates}


def join_script_lines(lines: Iterable[str]) -> str:
    """把多行命令拼成官方要求的脚本内容（每行以换行符结尾）。"""
    parts = [str(line).rstrip('\r\n') for line in lines]
    parts = [part for part in parts if part.strip()]
    return ''.join(f'{part}\n' for part in parts)


def _validate_choice(name: str, value: Any, choices: Sequence[str]) -> str:
    if value is None:
        raise ScnetValidationError(f'参数 {name} 不能为空，可选值: {list(choices)}')
    normalized = str(value)
    if normalized.lower() not in {item.lower() for item in choices}:
        raise ScnetValidationError(f'参数 {name}={value!r} 非法，可选值: {list(choices)}')
    return normalized


def _validate_positive(name: str, value: Any, *, allow_zero: bool = True) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ScnetValidationError(f'参数 {name} 必须是整数，收到 {value!r}') from None
    minimum = 0 if allow_zero else 1
    if number < minimum:
        raise ScnetValidationError(f'参数 {name} 不能小于 {minimum}，收到 {number}')
    return number


@dataclass
class MountInfo:
    """挂载信息（mountInfoList 元素）。"""

    source_path: str
    target_path: str
    type: str = 'data'

    def __post_init__(self) -> None:
        self.type = _validate_choice('mountInfoList.type', self.type, MOUNT_TYPES).lower()
        if not self.source_path or not self.target_path:
            raise ScnetValidationError('挂载的 sourcePath / targetPath 不能为空')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'sourcePath': self.source_path,
            'targetPath': self.target_path,
            'type': self.type,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'MountInfo':
        return cls(
            source_path=data.get('sourcePath', ''),
            target_path=data.get('targetPath', ''),
            type=data.get('type', 'data'),
        )


@dataclass
class PortInfo:
    """容器公开端口（containerPortInfoList 元素）。

    官方参数表标注 containerPort 为 int，但请求示例中以字符串 "18888" 传入，
    默认按示例以字符串发送；可传 as_string=False 改用整数。
    """

    container_port: int
    protocol_type: str = 'HTTP'
    as_string: bool = True

    def __post_init__(self) -> None:
        self.protocol_type = _validate_choice(
            'containerPortInfoList.protocolType', self.protocol_type, PROTOCOL_TYPES
        ).upper()
        self.container_port = _validate_positive(
            'containerPortInfoList.containerPort', self.container_port, allow_zero=False
        )

    def to_dict(self) -> Dict[str, Any]:
        port: Any = str(self.container_port) if self.as_string else self.container_port
        return {'protocolType': self.protocol_type, 'containerPort': port}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'PortInfo':
        return cls(
            container_port=int(data.get('containerPort', 0)),
            protocol_type=data.get('protocolType', 'HTTP'),
            as_string=isinstance(data.get('containerPort'), str),
        )


def _coerce_mounts(items: Iterable[Any]) -> Tuple[MountInfo, ...]:
    result = []
    for item in items or ():
        if isinstance(item, MountInfo):
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(MountInfo.from_dict(item))
        else:
            raise ScnetValidationError(f'挂载项类型不支持: {type(item).__name__}')
    return tuple(result)


def _coerce_ports(items: Iterable[Any]) -> Tuple[PortInfo, ...]:
    result = []
    for item in items or ():
        if isinstance(item, PortInfo):
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(PortInfo.from_dict(item))
        elif isinstance(item, (int, str)):
            result.append(PortInfo(container_port=int(item)))
        else:
            raise ScnetValidationError(f'端口项类型不支持: {type(item).__name__}')
    return tuple(result)


@dataclass
class ContainerSpec:
    """创建容器实例的请求体。

    `image_path` 与 `version` 需成对提供：官方示例
    imagePath=`10.0.35.26:5000/gpu/admin/base/jupyter:4.4-py3.7-cpu`、
    version=`jupyter:4.4-py3.7-cpu`。
    """

    instance_service_name: str
    image_path: str
    version: str
    resource_group: str
    accelerator_type: str = 'gpu'
    task_type: str = 'ssh'
    cpu_number: int = 1
    ram_size: int = 4096
    gpu_number: int = 0
    task_number: int = 1
    timeout_limit: str = 'unlimited'
    description: str = ''
    use_start_script: bool = False
    start_script_content: str = ''
    start_script_action_scope: str = 'all'
    mounts: Sequence[Any] = field(default_factory=tuple)
    ports: Sequence[Any] = field(default_factory=tuple)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ('instance_service_name', 'image_path', 'version', 'resource_group'):
            if not getattr(self, name):
                raise ScnetValidationError(f'参数 {name} 为必填项')
        self.accelerator_type = _validate_choice(
            'acceleratorType', self.accelerator_type, ACCELERATOR_TYPES
        ).lower()
        self.task_type = _validate_choice('taskType', self.task_type, TASK_TYPES).lower()
        self.start_script_action_scope = _validate_choice(
            'startScriptActionScope', self.start_script_action_scope, SCRIPT_ACTION_SCOPES
        ).lower()
        self.cpu_number = _validate_positive('cpuNumber', self.cpu_number, allow_zero=False)
        self.ram_size = _validate_positive('ramSize', self.ram_size, allow_zero=False)
        self.gpu_number = _validate_positive('gpuNumber', self.gpu_number)
        self.task_number = _validate_positive('taskNumber', self.task_number, allow_zero=False)
        self.use_start_script = bool(self.use_start_script)
        if self.use_start_script and not self.start_script_content:
            raise ScnetValidationError('useStartScript 为 True 时必须提供 start_script_content')
        if not self.timeout_limit:
            raise ScnetValidationError('参数 timeoutLimit 为必填项，例如 "01:00:00" 或 "unlimited"')
        self.mounts = _coerce_mounts(self.mounts)
        self.ports = _coerce_ports(self.ports)
        self.extra = dict(self.extra or {})

    @property
    def mount_info_list(self) -> Tuple[MountInfo, ...]:
        return tuple(self.mounts)

    @property
    def container_port_info_list(self) -> Tuple[PortInfo, ...]:
        return tuple(self.ports)

    def to_payload(self) -> Dict[str, Any]:
        """转换为官方请求体（camelCase）。"""
        payload: Dict[str, Any] = {
            'instanceServiceName': self.instance_service_name,
            'description': self.description,
            'taskType': self.task_type,
            'acceleratorType': self.accelerator_type,
            'version': self.version,
            'imagePath': self.image_path,
            'timeoutLimit': self.timeout_limit,
            'taskNumber': self.task_number,
            'resourceGroup': self.resource_group,
            'useStartScript': self.use_start_script,
            'startScriptActionScope': self.start_script_action_scope,
            'startScriptContent': self.start_script_content,
            'cpuNumber': self.cpu_number,
            'ramSize': self.ram_size,
            'gpuNumber': self.gpu_number,
        }
        if self.mounts:
            payload['mountInfoList'] = [item.to_dict() for item in self.mounts]
        if self.ports:
            payload['containerPortInfoList'] = [item.to_dict() for item in self.ports]
        # extra 最后合并，便于接入文档尚未覆盖的新字段
        payload.update(self.extra)
        return payload


@dataclass
class ResourceLimits:
    """节点资源限额（查询节点资源限额接口 data 字段）。"""

    cpu_number: Optional[int] = None
    gpu_number: Optional[int] = None
    mlu_limits: Optional[int] = None
    dcu_limits: Optional[int] = None
    nv_limits: Optional[int] = None
    memory_size: Optional[int] = None
    resource_group: Optional[str] = None
    node_number: Optional[int] = None
    max_time: Optional[str] = None
    id: Optional[str] = None
    user_name: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'ResourceLimits':
        data = data or {}
        return cls(
            cpu_number=data.get('cpuNumber'),
            gpu_number=data.get('gpuNumber'),
            mlu_limits=data.get('mluLimits'),
            dcu_limits=data.get('dcuLimits'),
            nv_limits=data.get('nvLimits'),
            memory_size=data.get('memorySize'),
            resource_group=data.get('resourceGroup'),
            node_number=data.get('nodeNumber'),
            max_time=data.get('maxTime'),
            id=data.get('id'),
            user_name=data.get('userName'),
        )


@dataclass
class ContainerInfo:
    """容器实例详情（查询容器实例详情接口 data 字段）。

    `status` 为容器执行状态；`raw` 保留服务端原始响应，便于读取文档未列出的字段。
    """

    id: str = ''
    status: str = ''
    instance_service_name: Optional[str] = None
    accelerator_type: Optional[str] = None
    task_type: Optional[str] = None
    resource_group: Optional[str] = None
    resource_spec: Optional[str] = None
    version: Optional[str] = None
    image_path: Optional[str] = None
    user_name: Optional[str] = None
    description: Optional[str] = None
    cpu_number: Optional[int] = None
    gpu_number: Optional[int] = None
    ram_size: Optional[int] = None
    task_number: Optional[Any] = None
    current_index: Optional[int] = None
    timeout_limit: Optional[str] = None
    create_time: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration: Optional[str] = None
    remaining_time: Optional[str] = None
    use_start_script: Optional[bool] = None
    start_script_content: Optional[str] = None
    start_script_path: Optional[str] = None
    start_script_action_scope: Optional[str] = None
    header_notebook_id: Optional[str] = None
    header_notebook_ip: Optional[str] = None
    tensorboard_id: Optional[str] = None
    tensorboard_path: Optional[str] = None
    mounts: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    ports: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    raw: Mapping[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ 状态
    @property
    def is_running(self) -> bool:
        """是否处于运行态（默认按 "running" 忽略大小写比较）。"""
        return status_matches(self.status, DEFAULT_RUNNING_STATUSES)

    @property
    def is_terminal(self) -> bool:
        """是否处于完成/失败/停止等终态（默认集合见模块常量）。"""
        return status_matches(self.status, DEFAULT_TERMINAL_STATUSES)

    def is_running_with(self, running_statuses: Iterable[str]) -> bool:
        """使用自定义运行态集合判断。"""
        return status_matches(self.status, running_statuses)

    def is_terminal_with(self, terminal_statuses: Iterable[str]) -> bool:
        """使用自定义终态集合判断。"""
        return status_matches(self.status, terminal_statuses)

    # -------------------------------------------------------------- 访问入口
    @property
    def access_urls(self) -> Tuple[str, ...]:
        """容器内已公开服务的访问入口集合。"""
        urls = []
        for item in self.ports or ():
            url = (item or {}).get('accessUrl')
            if url:
                urls.append(str(url))
        return tuple(urls)

    @property
    def mounted_paths(self) -> Tuple[Tuple[str, str], ...]:
        """(sourcePath, targetPath) 形式的挂载列表。"""
        return tuple(
            ((item or {}).get('sourcePath', ''), (item or {}).get('targetPath', ''))
            for item in self.mounts or ()
        )

    # ------------------------------------------------------------------ 构造
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'ContainerInfo':
        data = data or {}
        return cls(
            id=str(data.get('id') or ''),
            status=data.get('status') or '',
            instance_service_name=data.get('instanceServiceName'),
            accelerator_type=data.get('acceleratorType'),
            task_type=data.get('taskType'),
            resource_group=data.get('resourceGroup'),
            resource_spec=data.get('resourceSpec'),
            version=data.get('version'),
            image_path=data.get('imagePath'),
            user_name=data.get('userName'),
            description=data.get('description'),
            cpu_number=data.get('cpuNumber'),
            gpu_number=data.get('gpuNumber'),
            ram_size=data.get('ramSize'),
            task_number=data.get('taskNumber'),
            current_index=data.get('currentIndex'),
            timeout_limit=data.get('timeoutLimit'),
            create_time=data.get('createTime'),
            start_time=data.get('startTime'),
            end_time=data.get('endTime'),
            duration=data.get('duration'),
            remaining_time=data.get('remainingTime'),
            use_start_script=data.get('useStartScript'),
            start_script_content=data.get('startScriptContent'),
            start_script_path=data.get('startScriptPath'),
            start_script_action_scope=data.get('startScriptActionScope'),
            header_notebook_id=data.get('headerNotebookId'),
            header_notebook_ip=data.get('headerNotebookIp'),
            tensorboard_id=data.get('tensorboardId'),
            tensorboard_path=data.get('tensorboardPath'),
            mounts=tuple(data.get('mountInfoList') or ()),
            ports=tuple(data.get('containerPortInfoList') or ()),
            raw=dict(data),
        )

    def __str__(self) -> str:
        return f'<ContainerInfo id={self.id} status={self.status} spec={self.resource_spec}>'
