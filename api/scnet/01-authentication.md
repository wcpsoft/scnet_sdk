# 认证授权：获取访问凭证与授权区域

> 所有容器接口调用前必须先完成本文件中的两步。

---

## 一、获取访问凭证（推荐）

### 1. 接口说明

| 项目 | 内容 |
|---|---|
| 接口路径 | `https://api.scnet.cn/api/user/v3/tokens` |
| 请求方式 | `POST` |
| 请求数据类型 | `application/json` |
| 接口描述 | 区域资源用户认证，认证成功后返回各区域 ID、名称以及区域接口访问凭证 token |

官方备注：

1. 每次访问为用户可用的计算区域分别颁发一个 token，此 token 为访问其他服务接口的凭证，在后续接口请求中均需要携带。每个区域的 token 配合「获取授权区域」接口返回的 URL 地址，携带 token 调用作业、文件、容器等接口。
2. 若用户有某个区域的访问权限，但账户状态为停用状态时，则返回区域信息，但 token 为 `null`，无法调用后续接口，需充值后才能正常调用接口。
3. `clusterId` 为 `0`，`clusterName` 为 `ac` 的区域信息为平台自身 token，仅支持调用平台层面接口，如认证授权和用户资源及资源。

### 2. 请求头

| 名称 | 类型 | 必填 | 描述 | 示例 |
|---|---|---|---|---|
| `user` | string | 是 | 用户名 | `test` |
| `accessKey` | string | 是 | AK | `934e4dd887264b63a797ccb27f86048f` |
| `signature` | string | 是 | 签名 | `b86b8b86c98ce...` |
| `timestamp` | string | 是 | 秒级时间戳 | `1764597591` |

### 3. 签名算法

1. **获取授权码**：在个人中心 → 【访问控制】生成授权码并下载保存。`accessKey`（AK）与 `secretKey`（SK）对应下载文件中的 `Accesskey`、`Secretkey` 列。
2. **构造待签名消息**（JSON）：

```json
{"accessKey":"85f96a42b13f4d2c8b760d2775bbcca8","timestamp":"1764597591","user":"bob"}
```

3. **签名**：使用 `HMAC-SHA256` 算法、以 `secretKey`（SK）为密钥对该 JSON 字符串签名，结果为**16 进制字符串**，作为 `signature` 请求头传入。

### 4. 请求示例

**cURL**

```shell
curl --location --request POST 'https://api.scnet.cn/api/user/v3/tokens' \
--header 'accessKey: 934e4dd887264b63a797ccb27f86048f' \
--header 'signature: b2cfe85a136af1e3ff18898e' \
--header 'user: test' \
--header 'timestamp: 1764597591'
```

**Python**

```python
import hashlib
import hmac
import json
import time

import requests

USER = "test"
ACCESS_KEY = "934e4dd887264b63a797ccb27f86048f"
SECRET_KEY = "<SecretKey>"

timestamp = str(int(time.time()))
payload = {
    "accessKey": ACCESS_KEY,
    "timestamp": timestamp,
    "user": USER,
}
# 注意：签名的 JSON 需与下方待签名内容完全一致（key 顺序、无多余空格）
sign_message = json.dumps(payload, separators=(",", ":"))

signature = hmac.new(
    SECRET_KEY.encode("utf-8"),
    sign_message.encode("utf-8"),
    hashlib.sha256,
).hexdigest()

resp = requests.post(
    "https://api.scnet.cn/api/user/v3/tokens",
    headers={
        "user": USER,
        "accessKey": ACCESS_KEY,
        "signature": signature,
        "timestamp": timestamp,
    },
)
print(resp.text)
```

### 5. 返回参数

| 名称 | 类型 | 描述 | 示例 |
|---|---|---|---|
| `msg` | string | 信息 | `success` |
| `code` | string | 状态码 | `0` |
| `data` | array | 区域信息列表 | — |
| `data[].clusterName` | string | 区域名称 | `OpenAPI计算中心` |
| `data[].clusterId` | string | 区域 ID | `11112` |
| `data[].token` | string | 区域 token | `eyJhbGciOiJIUzI1NiIsInR5cC...` |

### 6. 返回示例

```json
{
  "msg": "success",
  "code": "0",
  "data": [
    {
      "clusterName": "OpenAPI计算中心",
      "clusterId": "11112",
      "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjb21wdXRlVXNlciI6Imhhb3dqIiwiYWNjb3VudFN0YXR1cyI6Ik93ZSIsImNyZWF0b3IiOiJhYyIsInJvbGUiOiIxIiwiZXhwaXJlVGltZSI6IjE2MzQyODY2MDMwNjYiLCJjbHVzdGVySWQiOiIxMTEyNiIsImludm9rZXIiOiJ4eHl5YWdlYSIsInVzZXIiOiJoYW93aiJ9.mprLWvhNLNK1YuQVLewnJ7AG10K644g38xAt-xO3GwY"
    },
    {
      "clusterName": "test中心",
      "clusterId": "111131",
      "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjb21wdXRlVXNlciI6Imhhb3dqIiwiYWNjb3VudFN0YXR1cyI6IkRpc2FibGUiLCJjcmVhdG9yIjoiYWMiLCJyb2xlIjoiMSIsImV4cGlyZVRpbWUiOiIxNjM0Mjg2NjAzMDgwIiwiY2x1c3RlcklkIjoiMTExMTMxIiwiaW52b2tlciI6Inh4eXlhZ2VhIiwidXNlciI6Imhhb3dqIn0.zKhISUwMa2Y16SH0LOBvfSJN_ctvABPUHMsjHj7vJfA"
    },
    {
      "clusterName": "ac",
      "clusterId": "0",
      "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjb21wdXRlVXNlciI6Imhhb3dqIiwiYWNjb3VudFN0YXR1cyI6Ik93ZSIsImNyZWF0b3IiOiJhYyIsInJvbGUiOiIxIiwiZXhwaXJlVGltZSI6IjE2MzQyODY2MDMwODciLCJjbHVzdGVySWQiOiIxMTEyNSIsImludm9rZXIiOiJ4eHl5YWdlYSIsInVzZXIiOiJoYW93aiJ9.bIGdJpUoCZaKSJB71o_ZKUBzpcdW4_y54afU_arRDIQ"
    }
  ]
}
```

> 使用返回列表中 **目标区域** 对应的 `token` 调用该区域的容器接口；`clusterId` 为 `0` 的 `ac` token 不能调用容器接口。

### 7. 错误码

| 错误码 | 说明 |
|---|---|
| 10001 | 内部错误 |
| 10003 | 参数不全 |
| 10004 | 参数无效 |
| 10008 | 权限不足 |
| 10009 | 校验失败 |
| 0 | 接口调用成功 |

---

## 二、获取授权区域

### 1. 接口说明

| 项目 | 内容 |
|---|---|
| 接口路径 | `https://www.scnet.cn/ac/openapi/v2/center` |
| 请求方式 | `GET` |
| 接口描述 | 获取授权区域，返回用户可用区域的信息及 url 地址、用户集群用户名及家目录等 |

官方备注：

- `hpcUrls` 为作业相关接口调用使用 url；`efileUrls` 为文件相应接口调用使用的 url；**`aiUrls` 为容器相应接口调用使用的 url**。
- 以上 Urls 若返回为多组 url 时，请根据返回中的 `enable` 参数进行地址可用性判断，为 `true` 时证明 url 可以正常使用。

### 2. 请求头

| 名称 | 类型 | 必填 | 描述 | 示例 |
|---|---|---|---|---|
| `token` | string | 是 | 计算区域接口凭证 | `eyJhbGciOiJIUzI1N...` |
| `Content-Type` | string | 否 | 文档示例中携带 | `application/json` |

### 3. 请求示例

```shell
curl --location 'https://www.scnet.cn/ac/openapi/v2/center' \
--header 'Content-Type: application/json' \
--header 'token: <Token>'
```

```python
import requests

response = requests.get(
    "https://www.scnet.cn/ac/openapi/v2/center",
    headers={
        "Content-Type": "application/json",
        "token": "<Token>",
    },
)
print(response.text)
```

### 4. 返回参数

| 名称 | 类型 | 描述 | 示例 |
|---|---|---|---|
| `msg` | string | 信息 | `success` |
| `code` | string | 状态码 | `0` |
| `data` | object | 区域信息 | — |
| `data.id` | string | 区域 ID | `11112` |
| `data.name` | string | 区域名称 | `OpenAPI计算中心` |
| `data.description` | string | 区域描述 | `对外OpenAPI中心` |
| `data.clusterUserInfo` | object | 区域用户信息 | — |
| `data.clusterUserInfo.userName` | string | 集群用户名 | `test` |
| `data.clusterUserInfo.homePath` | string | 家目录 | `/public/home/test` |
| `data.aiUrls` | string（实际为 array） | **容器服务访问信息** | — |
| `data.efileUrls` | string（实际为 array） | 文件服务访问信息 | — |
| `data.eshellUrls` | string（实际为 array） | eshell 服务访问信息 | — |
| `data.hpcUrls` | string（实际为 array） | 作业服务访问信息 | — |

### 5. 返回示例

```json
{
  "code": "0",
  "msg": "success",
  "data": {
    "id": 11112,
    "name": "OpenAPI计算中心",
    "description": "对外OpenAPI中心",
    "clusterUserInfo": {
      "userName": "test",
      "homePath": "/public/home/test"
    },
    "ingressUrls": [
      {
        "enable": "true",
        "isManagerNode": "true",
        "version": "5.2.2",
        "url": "https://www.scnet.cn"
      }
    ],
    "efileUrls": [
      {
        "nodeName": "h04r3n07",
        "enable": "true",
        "fastTransEnable": "true",
        "udpPort": "65104",
        "version": "2.6.1",
        "url": "{efileUrls}/efile"
      }
    ],
    "eshellUrls": [
      {
        "enable": "true",
        "version": "2.4.3",
        "url": "{eshellUrls}/eshell"
      }
    ],
    "hpcUrls": [
      {
        "enable": "true",
        "isManagerNode": "true",
        "version": "5.2.2",
        "url": "{hpcUrls}/hpc"
      }
    ],
    "aiUrls": [
      {
        "enable": "true",
        "version": "2.4.3",
        "url": "{hpcUrls}/ai"
      }
    ]
  }
}
```

> 取 `aiUrls` 中 `enable` 为 `"true"` 的元素，其 `url` 即容器接口的调用前缀（本文档中的 `{aiUrls}`）。

### 6. 错误码

| 错误码 | 说明 |
|---|---|
| 10001 | 内部错误 |
| 10003 | 参数不全 |
| 10004 | 参数无效 |
| 10008 | 权限不足 |
| 10009 | 没有权限访问接口 |
| 0 | 接口调用成功 |
