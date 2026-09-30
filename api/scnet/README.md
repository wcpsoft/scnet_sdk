# SCNet 计算服务开放 API（容器）文档

国家超算互联网平台（SCNet）Open API **2.0** 中与**容器实例**相关的接口整理。

- 官方文档：<https://www.scnet.cn/ac/openapi/doc/2.0/api/tutorials.html>
- 本目录文档均整理自官方公开文档，字段名与示例值保持原样。
- 基于本目录文档实现的 Python 类库封装见仓库根目录 [`README.md`](../../README.md)，代码位于仓库根的 `scnet_sdk/` 包内（容器创建 / 状态查询 / 脚本执行 / 删除，含配置分层、同步+异步客户端与多语言日志）。

---

## 一、文档索引

| 文件 | 内容 |
|---|---|
| [`01-authentication.md`](./01-authentication.md) | 获取访问凭证 `token`、获取授权区域 `aiUrls` |
| [`02-resources.md`](./02-resources.md) | 查询节点资源限额 |
| [`03-create-container.md`](./03-create-container.md) | **创建容器实例** |
| [`04-execute-script.md`](./04-execute-script.md) | 批量执行脚本 |
| [`05-container-status.md`](./05-container-status.md) | **查询容器实例详情（执行状态）** |
| [`06-delete-container.md`](./06-delete-container.md) | 批量删除容器 |

---

## 二、接口清单（容器相关）

| 步骤 | 接口 | 方法 | 路径 |
|---|---|---|---|
| 1 | 获取访问凭证 | `POST` | `https://api.scnet.cn/api/user/v3/tokens` |
| 2 | 获取授权区域（取容器服务 url） | `GET` | `https://www.scnet.cn/ac/openapi/v2/center` |
| 3 | 查询节点资源限额 | `GET` | `{aiUrls}/ai/openapi/v2/instance-service/resources` |
| 4 | 创建容器实例 | `POST` | `{aiUrls}/ai/openapi/v2/instance-service/task` |
| 5 | 批量执行脚本 | `POST` | `{aiUrls}/ai/openapi/v2/instance-service/task/actions/execute-script` |
| 6 | 查询容器实例详情 | `GET` | `{aiUrls}/ai/openapi/v2/instance-service/{id}/detail` |
| 7 | 批量删除容器 | `DELETE` | `{aiUrls}/ai/openapi/v2/instance-service/task?ids=xxx&ids=yyy` |

> 说明：上表第 3 步在官方「创建容器流程」中位于创建之前，用于确认可申请的 CPU / 内存 / 加速器上限。

---

## 三、调用流程

```
获取访问凭证 POST /api/user/v3/tokens
        │  （返回各区域 clusterId / clusterName / token）
        ▼
获取授权区域 GET /ac/openapi/v2/center
        │  （返回 aiUrls，取出 enable=true 的 url）
        ▼
查询节点资源限额 GET  {aiUrls}/ai/openapi/v2/instance-service/resources
        ▼
创建容器实例   POST {aiUrls}/ai/openapi/v2/instance-service/task   → data 为容器实例ID
        ▼
批量执行脚本   POST {aiUrls}/ai/openapi/v2/instance-service/task/actions/execute-script
        ▼
查询实例详情   GET  {aiUrls}/ai/openapi/v2/instance-service/{id}/detail  → data.status 为执行状态
        ▼
批量删除容器   DELETE {aiUrls}/ai/openapi/v2/instance-service/task?ids={id}
```

---

## 四、认证与地址约定

### 1. 认证方式

容器相关接口统一通过 **请求头 `token`** 鉴权（注意不是 `Authorization`）。

| Header | 类型 | 必填 | 描述 | 示例 |
|---|---|---|---|---|
| `token` | string | 是 | 接口凭证（区域 token） | `eyJhbGciOiJIUzI1...` |
| `Content-Type` | string | 视接口而定 | 请求体为 JSON 时需携带 | `application/json` |

### 2. `{aiUrls}` 的来源

`{aiUrls}` 为占位符，需从「获取授权区域」返回的 `aiUrls` 字段中取值（该字段实际为数组，应使用 `enable` 为 `true` 的元素）：

```json
"aiUrls": [
  { "enable": "true", "version": "2.4.3", "url": "{hpcUrls}/ai" }
]
```

> 官方文档将该字段类型标注为 `string`，但示例中为数组对象列表，解析时请以示例结构为准。

### 3. 注意事项

- 每个区域（clusterId）有独立的 token；`clusterId` 为 `0`、`clusterName` 为 `ac` 的 token 仅支持平台层面接口。
- 账户处于停用（Disable）状态时，区域信息仍会返回，但 `token` 为 `null`，无法调用后续接口。
- 请求示例中的域名 `10.0.35.26:5000/...` 等为镜像仓库地址，非调用地址。

---

## 五、通用响应结构

所有接口返回统一包装：

```json
{
  "code": "0",
  "msg": "success",
  "data": {}
}
```

| 名称 | 类型 | 描述 | 示例 |
|---|---|---|---|
| `code` | string | 状态码，`"0"` 表示成功 | `0` |
| `msg` | string | 信息 | `success` |
| `data` | object / array / string | 业务数据，不同接口含义不同 | — |

### 通用错误码（容器接口）

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

### 接口专属错误码

| 错误码 | 说明 | 所属接口 |
|---|---|---|
| 716020 | 查询数据库错误 | 批量执行脚本、批量删除容器 |
| 716864 | 执行脚本错误 | 批量执行脚本 |
| 716865 | 创建任务错误 | 创建容器实例 |
| 716866 | 删除任务失败 | 批量删除容器 |
| 716870 | 实例数量错误 | 批量执行脚本 |
