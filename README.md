# scnet-sdk

SCNet（国家超算互联网）开放 API 的 Python 类库封装，覆盖**容器创建、状态查询（执行状态）、脚本执行与删除**，提供**同步 + 异步（asyncio）双栈**客户端。

接口与字段严格对齐 [`api/scnet/`](../api/scnet/) 目录下的官方文档整理：

| 文档 | 对应能力 |
|---|---|
| [`api/scnet/01-authentication.md`](../api/scnet/01-authentication.md) | AK/SK 签名获取 `token`、解析容器服务地址 `aiUrls` |
| [`api/scnet/02-resources.md`](../api/scnet/02-resources.md) | 查询节点资源限额 |
| [`api/scnet/03-create-container.md`](../api/scnet/03-create-container.md) | **创建容器实例** |
| [`api/scnet/04-execute-script.md`](../api/scnet/04-execute-script.md) | 批量执行脚本 |
| [`api/scnet/05-container-status.md`](../api/scnet/05-container-status.md) | **查询容器实例详情 / 执行状态** |
| [`api/scnet/06-delete-container.md`](../api/scnet/06-delete-container.md) | 批量删除容器 |

## 目录结构（标准 Python 包布局）

```
scnet_sdk/                     # 项目根
├── pyproject.toml             # PEP 621 打包元数据（setuptools 后端）
├── README.md
├── scnet_sdk/                 # 包
│   ├── __init__.py            # 对外导出
│   ├── config.py              # 配置加载：系统态 + 用户态
│   ├── defaults.yaml          # 类库系统态配置（随包发布，只读）
│   ├── auth.py                # AK/SK 签名、获取 token、解析 aiUrls（同步 + 异步）
│   ├── _http.py               # 请求 / 响应解包（api_request / api_request_async）
│   ├── base.py                # 同步/异步共享基类与纯逻辑
│   ├── client.py              # ScnetClient / ContainerHandle（同步）
│   ├── aclient.py             # AsyncScnetClient / AsyncContainerHandle（asyncio）
│   ├── models.py              # ContainerSpec / ContainerInfo / ResourceLimits / MountInfo / PortInfo
│   └── errors.py              # 异常体系 + 官方错误码表
├── examples/
│   ├── scnet.yaml             # 用户态配置示例
│   ├── create_and_wait.py     # 同步：创建 + 等就绪 + 执行 + 删除
│   ├── create_and_wait_async.py   # 异步：同一流程 + 并发等待示例
│   └── query_status.py
└── tests/
    ├── test_scnet_sdk.py      # 同步客户端与模型用例
    ├── test_async_client.py   # 异步客户端用例（含同步/异步报文一致性）
    └── test_config.py         # 配置系统用例
```

## 安装

```bash
cd scnet_sdk

# 开发模式安装（推荐，之后可在任意目录 import scnet_sdk）
python -m pip install -e .

# 或只装依赖并直接在当前目录使用
python -m pip install httpx PyYAML
```

依赖：`httpx>=0.27,<1.0`、`PyYAML>=6.0`（Python >= 3.9）。

## 配置体系：系统态 + 用户态

配置分两层，加载后深合并，**列表整体替换、映射逐层合并**：

| 层级 | 载体 | 内容 | 谁维护 |
|---|---|---|---|
| **类库系统态** | `scnet_sdk/defaults.yaml`（包内资源，只读） | 接口地址 `endpoints`、接口路径 `paths`、超时 `timeouts`、状态集合 `statuses` | 类库维护，随版本发布 |
| **用户态** | 用户自己的 YAML | 凭证（`user`/`access_key`/`secret_key` 或 `token`）、区域 `cluster_id`、`ai_url`，以及任意系统态覆盖项 | 使用者维护 |

优先级（低 → 高）：

```
代码内置默认值  <  系统态 defaults.yaml  <  用户态 YAML  <  SCNET_* 环境变量  <  代码传参
```

### 用户态文件查找顺序

1. 显式传入的 `config_path`（不存在则报错，不会静默忽略）
2. 环境变量 `SCNET_CONFIG` 指向的文件（不存在则报错）
3. `./scnet.yaml` 或 `./scnet.yml`
4. `~/.config/scnet/scnet.yaml`（或 `.yml`）
5. `~/.scnet.yaml`（或 `.yml`）

### 用户态配置示例（`examples/scnet.yaml`）

```yaml
# 凭证与区域
cluster_id: "11112"
user: your-user
access_key: your-access-key
secret_key: your-secret-key
# token: eyJhbGciOiJIUzI1...        # 已有 token 时可替代 AK/SK
# ai_url: https://<域名>/ai          # 一般无需填写，SDK 自动解析

# 覆盖系统态项（可选）
timeouts:
  wait: 3600
  poll_interval: 3

statuses:
  running:
    - running
    - deploying
```

### 系统态配置（`scnet_sdk/defaults.yaml`）

```yaml
endpoints:
  token_url: https://api.scnet.cn/api/user/v3/tokens
  center_url: https://www.scnet.cn/ac/openapi/v2/center
paths:
  resources: /openapi/v2/instance-service/resources
  task: /openapi/v2/instance-service/task
  execute_script: /openapi/v2/instance-service/task/actions/execute-script
  detail: /openapi/v2/instance-service/{container_id}/detail
timeouts:
  request: 30.0        # 单次 HTTP 请求超时（秒）
  wait: 1800.0         # 等待容器就绪总时长上限（秒）
  poll_interval: 5.0   # 状态轮询间隔（秒）
statuses:
  running: [running]
  terminal: [finished, complete, completed, success, succeeded,
             failed, failure, error, stopped, stop, canceled, cancelled]
```

配置键校验严格：出现未知配置段或未知键会直接抛 `ScnetConfigError`，避免拼写错误被静默忽略。

### 支持的环境变量

| 变量 | 覆盖项 |
|---|---|
| `SCNET_CONFIG` | 用户态配置文件路径 |
| `SCNET_USER` / `SCNET_ACCESS_KEY` / `SCNET_SECRET_KEY` | 凭证 |
| `SCNET_TOKEN` / `SCNET_AI_URL` / `SCNET_CLUSTER_ID` | 凭证与区域 |
| `SCNET_TOKEN_URL` / `SCNET_CENTER_URL` | 认证接口地址 |
| `SCNET_REQUEST_TIMEOUT` / `SCNET_WAIT_TIMEOUT` / `SCNET_POLL_INTERVAL` | 超时 |
| `SCNET_RUNNING_STATUSES` / `SCNET_TERMINAL_STATUSES` | 状态集合（逗号分隔） |
| `SCNET_SIGNING_COMPACT` | 签名字符串是否紧凑 |

## 快速开始

### 1. 创建客户端

```python
from scnet_sdk import ScnetClient

# 自动加载：系统态 + 用户态 YAML + 环境变量；带 AK/SK 时自动完成两步认证
with ScnetClient.from_config() as client:
    print(client.describe_config())      # 脱敏后的配置摘要，便于排查
    print(client.ai_url)                 # https://<容器服务域名>/ai
```

其它入口：

```python
ScnetClient.from_config('path/to/scnet.yaml')            # 指定用户态文件
ScnetClient.from_credentials(user, ak, sk, cluster_id='11112')   # 显式 AK/SK
ScnetClient.from_environment()                            # 仅用 SCNET_* 环境变量
ScnetClient(config)                                       # 传入已构造的 ScnetConfig
```

### 2. 创建容器实例

```python
from scnet_sdk import ContainerSpec, MountInfo, PortInfo

spec = ContainerSpec(
    instance_service_name='Instances_2205113838',
    image_path='10.0.35.26:5000/gpu/admin/base/jupyter:4.4-py3.7-cpu',
    version='jupyter:4.4-py3.7-cpu',
    resource_group='TeslaM40',
    accelerator_type='gpu',          # mlu | dcu | gpu | cpu
    task_type='ssh',                 # ssh | jupyter | codeserver | rstudio
    cpu_number=3,
    ram_size=15360,                  # MB
    gpu_number=1,
    timeout_limit='unlimited',       # 或 '01:00:00'
    mounts=[MountInfo('/public1/home/u/test_mount', '/mnt/test_mount', 'data')],
    ports=[PortInfo(18888, 'HTTP')],
)
container_id = client.create_container(spec)   # 文档返回的 data 即容器实例 ID
```

创建前可先确认配额：

```python
limits = client.resource_limits('TeslaM40', 'gpu')
print(limits.cpu_number, limits.gpu_number, limits.memory_size, limits.max_time)
```

### 3. 查询执行状态

```python
info = client.get_container(container_id)      # 等价写法：client.get_container_status(...)
print(info.status, info.resource_spec, info.access_urls)
print(info.is_running, info.is_terminal)
```

轮询等待就绪（超时参数默认取自配置的 `timeouts.wait` / `timeouts.poll_interval`）：

```python
info = client.wait_for_container(
    container_id,
    timeout=1800,
    poll_interval=5,
    on_poll=lambda attempt, i: print(attempt, i.status),
)
```

### 4. 执行脚本 / 删除容器

```python
from scnet_sdk import join_script_lines

script = join_script_lines(['cd /public/home/u/project', 'python train.py'])
client.execute_script(container_id, script, scope='all')   # all | header
client.delete_containers([container_id])
```

### 5. 便捷写法：临时容器自动清理

```python
with client.open_container(spec) as container:
    print(container.id, container.status)
    container.execute('echo "hello world"')
# 退出 with 后自动删除；keep=True 可保留
```

## 异步用法（asyncio）

`AsyncScnetClient` 与同步客户端**能力、语义、请求体完全一致**，区别只有两点：传输层用 `httpx.AsyncClient`，等待轮询用 `asyncio.sleep` 而非 `time.sleep`。因此可直接放进 FastAPI 路由、asyncio 任务编排，不会阻塞事件循环。

```python
import asyncio
from scnet_sdk import AsyncScnetClient, ContainerSpec, join_script_lines

async def main():
    # 注意：from_config / from_credentials / from_environment 是协程方法，需要 await
    async with await AsyncScnetClient.from_config('scnet.yaml') as client:
        container_id = await client.create_container(spec)
        info = await client.wait_for_container(container_id, poll_interval=5)
        await client.execute_script(container_id, join_script_lines(['echo hi']))
        await client.delete_containers([container_id])

asyncio.run(main())
```

与同步版的对应关系：

| 同步 | 异步 |
|---|---|
| `ScnetClient.from_config(...)` | `await AsyncScnetClient.from_config(...)` |
| `with client:` | `async with client:`（退出时 `await aclose()`） |
| `client.create_container(spec)` | `await client.create_container(spec)` |
| `client.wait_for_container(cid, on_poll=fn)` | `await client.wait_for_container(cid, on_poll=fn)`，`fn` 可为普通函数或协程函数 |
| `with client.open_container(spec) as c:` | `async with client.open_container(spec) as c:` |
| `c.status` / `c.info` / `c.access_urls`（属性） | `await c.status()` / `await c.info()` / `await c.access_urls()`（协程方法） |
| `client.close()` | `await client.aclose()` |

异步独有的收益——并发等待/操作多个容器：

```python
infos = await asyncio.gather(
    *(client.wait_for_container(cid) for cid in container_ids)
)
```

认证侧同样提供异步函数：`fetch_tokens_async` / `fetch_center_async` / `obtain_credentials_async`。

## 异常体系

| 异常 | 触发场景 |
|---|---|
| `ScnetConfigError` | 配置缺失/非法、缺 token、配置文件不存在或键名未知 |
| `ScnetValidationError` | 本地参数非法（枚举值、必填项、数值范围） |
| `ScnetAuthError` | 签名不通过、token 失效、区域无权限、账号停用 |
| `ScnetTransportError` | 连接失败或请求超时 |
| `ScnetResponseError` | 响应非 JSON 或结构不符合约定 |
| `ScnetApiError` | 业务错误码非 `0`，带 `code` / `payload` |
| `ScnetStateError` | 容器进入失败终态（等待就绪时） |
| `ScnetTimeoutError` | 等待容器就绪超时 |

```python
from scnet_sdk import ScnetApiError, describe_code

try:
    client.create_container(spec)
except ScnetApiError as exc:
    print(exc.code, describe_code(exc.code), exc.message)   # 例如 716865 创建任务错误
```

内置官方错误码表（`ERROR_MESSAGES`）：`0/10001/10003/10004/10007/10008/10009/10010/10011/10012/716020/716864/716865/716866/716870`。

## 状态（`status`）说明

官方开放 API 文档**未给出 `status` 的完整英文枚举**，示例中只出现过 `Waiting`；控制台帮助文档描述的 6 种状态为：等待 / 部署 / 运行 / 完成 / 失败 / 停止。

SDK 因此采用**可配置 + 忽略大小写**的匹配策略，默认值来自系统态配置，可在用户态 YAML 或代码中覆盖：

```yaml
statuses:
  running: [running, deploying]
  terminal: [failed, stopped, finished]
```

```python
client.wait_for_container(cid, running_statuses=('deploying',))
```

## 设计要点与已知假设

1. **容器服务地址**：文档路径为 `{aiUrls}/ai/openapi/v2/...`，而授权区域返回的 `aiUrls[].url` 形如 `{hpcUrls}/ai`。SDK 按「`url` 即服务根地址（含 `/ai`）」处理并自动补齐 `/ai` 后缀；线上路径不同时请在用户态配置中直接写明 `ai_url`。
2. **`containerPort` 类型**：官方参数表标注 `int`，示例传字符串 `"18888"`。SDK 默认按示例以字符串发送，`PortInfo(18888, as_string=False)` 可改为整数。
3. **`startScriptContent` 换行**：文档要求多行命令每行以换行符结尾，`join_script_lines()` 用于生成。
4. **`extra` 逃生舱**：`ContainerSpec(extra={...})` 会覆盖/追加任意请求字段，便于接入文档未覆盖的新参数。
5. **`open_container` 清理失败不掩盖业务异常**：只发 `warnings.warn`，需人工清理时容器 ID 会在告警中给出。
6. **凭证脱敏**：`ScnetConfig.describe()` / `ScnetClient.describe_config()` 输出的 AK/SK/token 均已打码，可直接打日志。
7. **同步/异步不重复实现**：配置解析、请求体构造、响应解析、等待判定等纯逻辑集中在 `base.py`，`client.py` / `aclient.py` 只各自实现传输与轮询；两者共用同一份 `models` / `errors`，因此报文与异常语义天然一致（有专门的一致性用例兜底）。

## 测试

```bash
cd scnet_sdk
python -m unittest discover -s tests -t . -v
```

共 **84** 个用例（同步 60 + 异步 24），全部基于 `httpx.MockTransport` 与临时目录中的 YAML，不发起真实网络请求，也不依赖本机 `~/.config` 状态；其中包含一组「同一 spec 下同步与异步发出的 JSON 报文完全一致」的一致性用例。
