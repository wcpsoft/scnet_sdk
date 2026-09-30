# 查询节点资源限额

创建容器前用于确认可申请的 CPU / 内存 / 加速器上限。

---

## 一、接口说明

| 项目 | 内容 |
|---|---|
| 接口路径 | `{aiUrls}/ai/openapi/v2/instance-service/resources` |
| 请求方式 | `GET` |
| 接口描述 | 获取节点资源限额 |

---

## 二、请求消息

### 1. 请求头

| 名称 | 类型 | 必填 | 描述 | 示例 |
|---|---|---|---|---|
| `token` | string | 是 | 接口凭证 | `eyJhbGciOiJIUzI1...` |

### 2. 请求参数（Query）

| 名称 | 类型 | 必填 | 描述 | 示例 |
|---|---|---|---|---|
| `acceleratorType` | string | 是 | 加速器类型 | `gpu` |
| `resourceGroup` | string | 是 | 资源分组 | `TeslaM40` |

### 3. 完整请求地址

```
{aiUrls}/ai/openapi/v2/instance-service/resources?resourceGroup=TeslaM40&acceleratorType=gpu
```

### 4. 请求示例

**cURL**

```shell
curl --location '{aiUrls}/ai/openapi/v2/instance-service/resources?resourceGroup=TeslaM40&acceleratorType=gpu' \
--header 'token: <Token>'
```

**Python**

```python
import requests

url = "{aiUrls}/ai/openapi/v2/instance-service/resources?resourceGroup=TeslaM40&acceleratorType=gpu"
headers = {"token": "<Token>"}

response = requests.request("GET", url, headers=headers)
print(response.text)
```

---

## 三、响应消息

### 1. 返回参数

| 名称 | 类型 | 描述 | 示例 |
|---|---|---|---|
| `msg` | string | 信息 | `success` |
| `code` | string | 状态码 | `0` |
| `data` | object | 节点资源限额信息 | — |
| `data.id` | string | 容器 ID | `null` |
| `data.cpuNumber` | int | 单节点 CPU 核心数量 | `40` |
| `data.mluLimits` | int | 单节点 MLU 卡数限额 | `0` |
| `data.dcuLimits` | int | 单节点 DCU 卡数限额 | `0` |
| `data.nvLimits` | int | 单节点 GPU 卡数限额 | `0` |
| `data.gpuNumber` | int | 单节点 GPU 数量 | `2` |
| `data.memorySize` | int | 单节点最大内存（MB） | `31888` |
| `data.resourceGroup` | string | 资源分组 | `TeslaM40` |
| `data.userName` | string | 用户名 | `null` |
| `data.nodeNumber` | int | 队列的节点数量 | `1` |
| `data.maxTime` | string | 任务最大运行时间 | `unlimited` |

### 2. 返回示例

```json
{
  "code": "0",
  "msg": "success",
  "data": {
    "id": null,
    "cpuNumber": 40,
    "mluLimits": 0,
    "dcuLimits": 0,
    "nvLimits": 0,
    "gpuNumber": 2,
    "memorySize": 31888,
    "resourceGroup": "TeslaM40",
    "userName": null,
    "nodeNumber": 1,
    "maxTime": "unlimited"
  }
}
```

---

## 四、错误码

| 错误码 | 说明 |
|---|---|
| 0 | 成功 |
| 10001 | 内部异常（其他异常） |
| 10003 | 参数不全 |
| 10004 | 参数无效 |
| 10007 | 用户已被冻结 |
| 10008 | 权限不足 |
| 10009 | 没有权限访问接口 |
| 10010 | 文件校验失败 |
| 10011 | 文件过大 |
| 10012 | 连接中断 |

---

## 五、要点提示

- `resourceGroup` 与 `acceleratorType` 均为**必填**，缺省可能触发 `10003`（参数不全）。
- `data.userName`、`data.id` 在示例中为 `null`；`data.maxTime` 可能为 `"unlimited"` 或具体时间字符串。
- 区分 `nvLimits`（GPU 卡数限额）与 `gpuNumber`（GPU 数量）。
- 本接口返回的 `cpuNumber` / `memorySize` / `gpuNumber` 可作为创建容器时 `cpuNumber` / `ramSize` / `gpuNumber` 的取值上限参考。
