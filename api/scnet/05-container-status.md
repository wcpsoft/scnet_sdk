# 查询容器实例详情（执行状态）

> 官方开放 API 中**没有独立的「查询容器执行状态」接口**，容器执行状态通过本接口返回的 `data.status` 字段体现。

---

## 一、接口说明

| 项目 | 内容 |
|---|---|
| 接口路径 | `{aiUrls}/ai/openapi/v2/instance-service/{id}/detail` |
| 请求方式 | `GET` |
| 请求数据类型 | （官方文档未填写） |
| 接口描述 | 查询容器实例详情 |

---

## 二、请求消息

### 1. 请求头

| 名称 | 类型 | 必填 | 描述 | 示例 |
|---|---|---|---|---|
| `token` | string | 是 | 接口凭证 | `eyJhbGciOiJIUzI1...` |

### 2. 路径参数

| 名称 | 类型 | 必填 | 描述 | 示例 |
|---|---|---|---|---|
| `id` | string | 是 | 容器实例 ID | `4c1f43ddb030483e89b55413bee6c004` |

> `id` 来自「创建容器实例」接口返回的 `data`。

### 3. 完整请求地址

```
{aiUrls}/ai/openapi/v2/instance-service/{id}/detail
```

### 4. 请求示例

**cURL**

```shell
curl --location '{aiUrls}/ai/openapi/v2/instance-service/4c1f43ddb030483e89b55413bee6c004/detail' \
--header 'token: <Token>'
```

**Python**

```python
import requests

url = "{aiUrls}/ai/openapi/v2/instance-service/4c1f43ddb030483e89b55413bee6c004/detail"
headers = {"token": "<Token>"}

response = requests.request("GET", url, headers=headers)
print(response.text)
```

**Java（OkHttp）**

```java
import okhttp3.*;

public class QueryContainerDetailDemo {

    public static final String TOKEN = "<Token>";

    public static void main(String[] args) throws Exception {
        OkHttpClient client = new OkHttpClient().newBuilder()
                .build();
        Request request = new Request.Builder()
                .url("{aiUrls}/ai/openapi/v2/instance-service/4c1f43ddb030483e89b55413bee6c004/detail")
                .method("GET", null)
                .addHeader("token", TOKEN)
                .build();
        Response response = client.newCall(request).execute();
        System.out.println(response.body().string());
    }
}
```

---

## 三、响应消息

### 1. 返回参数

| 名称 | 类型 | 描述 | 示例 |
|---|---|---|---|
| `msg` | string | 信息 | `SUCCESS` |
| `code` | string | 状态码 | `0` |
| `data` | object | 容器详情 | — |
| `data.id` | string | 容器实例 ID | `4c1f43ddb030483e89b55413bee6c004` |
| `data.headerNotebookId` | string | 容器实例关联的首个 notebook 任务 ID | — |
| `data.instanceServiceName` | string | 名称 | `Instances_2205113837` |
| `data.currentIndex` | int | 容器当前索引 | `2` |
| `data.gpuNumber` | int | GPU 数量 | `1` |
| `data.cpuNumber` | int | CPU 数量 | `3` |
| `data.ramSize` | int | 内存（MB） | `15360` |
| `data.acceleratorType` | string | 加速器类型 | `gpu` |
| `data.resourceGroup` | string | 资源分组 | `TeslaM40` |
| `data.resourceSpec` | string | 资源配置 | `3 核心; 1 加速器; 15.0G 内存` |
| `data.taskNumber` | string | 实例任务数量 | `1` |
| `data.timeoutLimit` | string | 超时时间 | `unlimited` |
| `data.userName` | string | 用户名 | `magic2` |
| `data.version` | string | 镜像名称 | `jupyter:4.4-py3.7-cpu` |
| `data.imagePath` | string | 镜像路径 | `10.0.35.26:5000/...` |
| **`data.status`** | **string** | **状态（执行状态）** | **`Waiting`** |
| `data.taskType` | string | 任务类型 | `ssh` |
| `data.description` | string | 描述信息 | — |
| `data.createTime` | string | 创建时间 | `2022-05-11 19:30:34` |
| `data.startTime` | string | 开始时间 | `null` |
| `data.endTime` | string | 结束时间 | `null` |
| `data.duration` | string | 持续时间 | `--` |
| `data.remainingTime` | string | 剩余时间 | `--` |
| `data.tensorboardId` | string | TB-ID | `null` |
| `data.tensorboardPath` | string | TB 路径 | `null` |
| `data.mountInfoList` | array | 容器挂载信息集合 | `[]` |
| `data.mountInfoList.sourcePath` | string | 挂载路径 | — |
| `data.mountInfoList.type` | string | 类型 | — |
| `data.containerPortInfoList` | array | 容器公开服务的端口信息集合 | `[]` |
| `data.containerPortInfoList.accessUrl` | string | 用户访问容器内服务的入口 | — |
| `data.containerPortInfoList.containerPort` | string | 容器内已经开放的端口 | — |
| `data.containerPortInfoList.protocolType` | string | 协议类型 | — |
| `data.useStartScript` | boolean | 启用脚本 | `false` |
| `data.startScriptContent` | string | 启动脚本的内容 | `""` |
| `data.startScriptPath` | string | 启动脚本路径 | `null` |
| `data.startScriptActionScope` | string | 启用脚本范围 | `all` |

> 返回示例中还存在参数表未列出的字段 `data.headerNotebookIp`（值为 `null`），此处按原样保留。

### 2. 返回示例

```json
{
  "code": "0",
  "msg": "SUCCESS",
  "data": {
    "id": "4c1f43ddb030483e89b55413bee6c004",
    "headerNotebookId": "1a07f501dc89459686996a26ef521abb",
    "instanceServiceName": "Instances_2205113837",
    "currentIndex": 2,
    "gpuNumber": 1,
    "cpuNumber": 3,
    "ramSize": 15360,
    "acceleratorType": "gpu",
    "resourceGroup": "TeslaM40",
    "resourceSpec": "3 核心; 1 加速器; 15.0G 内存",
    "taskNumber": 1,
    "timeoutLimit": "unlimited",
    "userName": "magic2",
    "version": "jupyter:4.4-py3.7-cpu",
    "imagePath": "10.0.35.26:5000/gpu/admin/base/jupyter:4.4-py3.7-cpu",
    "status": "Waiting",
    "taskType": "ssh",
    "description": "",
    "createTime": "2022-05-11 19:30:34",
    "startTime": null,
    "endTime": null,
    "duration": "--",
    "remainingTime": "--",
    "tensorboardId": null,
    "tensorboardPath": null,
    "mountInfoList": [],
    "containerPortInfoList": [],
    "useStartScript": false,
    "startScriptContent": "",
    "startScriptPath": null,
    "startScriptActionScope": "all",
    "headerNotebookIp": null
  }
}
```

---

## 四、容器状态（`data.status`）

官方开放 API 文档中**未给出 `status` 的完整枚举清单**，返回值示例仅出现过 `Waiting`。

超算互联网控制台帮助文档对容器实例「状态」列的描述为 **6 种**，可供对照参考（官方原文只给出中文名称与含义，**未给出英文枚举值**）：

| 序号 | 中文状态 | 含义（官方原文） | 对应 `status` 枚举 |
|---|---|---|---|
| 1 | 等待 | 任务已创建成功，正在等待计算资源 | `Waiting`（API 示例中已确认） |
| 2 | 部署 | 正在部署执行任务的环境 | 未提供 |
| 3 | 运行 | 任务正在运行 | 未提供 |
| 4 | 完成 | 任务已经执行完成 | 未提供 |
| 5 | 失败 | 任务执行失败 | 未提供 |
| 6 | 停止 | 任务被中止 | 未提供 |

> 除 `Waiting` 外，其余英文取值**无法从官方文档确认**，请以实际接口返回值为准，不要按推测硬编码。

相关约束：SSH 访问容器、Jupyter 服务「进入」等操作**仅在状态为「运行」时可用**。

---

## 五、轮询等待容器就绪（示例）

创建容器后状态需要轮询确认，直到进入运行态：

```python
import time

import requests

AI_URLS = "<aiUrls>"
TOKEN = "<Token>"
INSTANCE_ID = "4c1f43ddb030483e89b55413bee6c004"

RUNNING = "Running"          # 以实际返回的枚举值为准
TERMINAL = {"Failed", "Stopped", "Finished"}

url = f"{AI_URLS}/ai/openapi/v2/instance-service/{INSTANCE_ID}/detail"
headers = {"token": TOKEN}

while True:
    resp = requests.get(url, headers=headers).json()
    if resp.get("code") != "0":
        raise RuntimeError(f"查询失败: {resp.get('code')} {resp.get('msg')}")

    data = resp["data"]
    status = data["status"]
    print(f"status={status} duration={data.get('duration')}")

    if status == RUNNING:
        print("容器已就绪:", data.get("resourceSpec"))
        break
    if status in TERMINAL:
        raise RuntimeError(f"容器未进入运行态: {status}")

    time.sleep(5)
```

---

## 六、错误码

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

## 七、要点提示

- 调用方式：`GET {aiUrls}/ai/openapi/v2/instance-service/{容器实例ID}/detail`，仅需在 Header 携带 `token`。
- 状态字段为 `data.status`；**枚举与含义官方文档缺失**，除 `Waiting` 外的取值需自行核实。
- 时间字段（`createTime`、`startTime`、`endTime`、`duration`、`remainingTime`）在未就绪时可能返回 `null` 或 `"--"`。
- `containerPortInfoList[].accessUrl` 可用于访问容器内已公开的服务（如 Jupyter）。
