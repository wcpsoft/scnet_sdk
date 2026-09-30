# 创建容器实例

---

## 一、接口说明

| 项目 | 内容 |
|---|---|
| 接口路径 | `{aiUrls}/ai/openapi/v2/instance-service/task` |
| 请求方式 | `POST` |
| 请求数据类型 | `application/json`（官方文档该字段为空，请求示例使用 JSON） |
| 接口描述 | 创建容器实例 |

---

## 二、请求消息

### 1. 请求头

| 名称 | 类型 | 必填 | 描述 | 示例 |
|---|---|---|---|---|
| `token` | string | 是 | 接口凭证 | `eyJhbGciOiJIUzI1...` |
| `Content-Type` | string | 是 | 请求体为 JSON | `application/json` |

### 2. 请求参数（Body，JSON）

| 名称 | 类型 | 必填 | 描述 | 示例 |
|---|---|---|---|---|
| `acceleratorType` | string | 是 | 加速器类型，包括：`mlu`、`dcu`、`gpu`、`cpu` | `gpu` |
| `containerPortInfoList` | array | 否 | 服务端口 | — |
| ├ `containerPort` | int | 是 | 端口 | `18888` |
| └ `protocolType` | string | 是 | 协议类型，包括：`SSH` \| `HTTP` | `HTTP` |
| `cpuNumber` | int | 是 | CPU 数量 | `3` |
| `description` | string | 否 | 描述信息 | `""` |
| `gpuNumber` | int | 是 | GPU 数量 | `1` |
| `imagePath` | string | 是 | 镜像路径 | `10.0.35.26:5000/gpu/admin/base/jupyter:4.4-py3.7-cpu` |
| `instanceServiceName` | string | 是 | 名称 | `Instances_2205113838` |
| `mountInfoList` | array | 否 | 挂载信息 | — |
| ├ `sourcePath` | string | 是 | 源路径 | `/public/home/username/source_mount` |
| ├ `targetPath` | string | 是 | 目标路径 | `/mnt/test_mount` |
| └ `type` | string | 是 | 类型，包括：`data` \| `path` | `data` |
| `ramSize` | int | 是 | 内存，单位为 MB | `15360` |
| `resourceGroup` | string | 是 | 资源分组 | `TeslaM40` |
| `startScriptActionScope` | string | 是 | 启动脚本范围：`all` 代表所有容器，`header` 代表首个容器 | `all` |
| `startScriptContent` | string | 当 `useStartScript` 为 `true` 时必填 | 启动脚本的内容；多行命令时需在每行末尾加入 `\n` 换行转义符 | `""` |
| `taskNumber` | int | 是 | 实例任务数量 | `1` |
| `taskType` | string | 是 | 任务类型，包括：`ssh` \| `jupyter` \| `codeserver` \| `rstudio` | `ssh` |
| `timeoutLimit` | string | 是 | 自动停止时间 | `01:00:00` |
| `useStartScript` | boolean | 是 | 启用脚本，`true` 代表启用，默认为 `false` | `false` |
| `version` | string | 是 | 镜像名称 | `jupyter:4.4-py3.7-cpu` |

> 注意：
> - 参数表中 `containerPort` 类型标注为 `int`，但请求示例中以字符串 `"18888"` 传入。
> - 参数表中 `timeoutLimit` 示例为 `01:00:00`，请求示例中使用了 `unlimited`，实际取值需与平台确认。

### 3. 请求示例

**cURL**

```shell
curl --location '{aiUrls}/ai/openapi/v2/instance-service/task' \
--header 'token: <Token>' \
--header 'Content-Type: application/json' \
--data '{
    "instanceServiceName": "Instances_2205113838",
    "description": "",
    "taskType": "ssh",
    "acceleratorType": "gpu",
    "version": "jupyter:4.4-py3.7-cpu",
    "imagePath": "10.0.35.26:5000/gpu/admin/base/jupyter:4.4-py3.7-cpu",
    "timeoutLimit": "unlimited",
    "taskNumber": 1,
    "resourceGroup": "TeslaM40",
    "useStartScript": false,
    "startScriptActionScope": "all",
    "startScriptContent": "",
    "cpuNumber": 3,
    "ramSize": 15360,
    "gpuNumber": 1,
    "mountInfoList": [
        {
            "sourcePath": "/public1/home/lizb0530d/test_mount",
            "targetPath": "/mnt/test_mount",
            "type": "data"
        }
    ],
    "containerPortInfoList": [
        {
            "protocolType": "HTTP",
            "containerPort": "18888"
        }
    ]
}'
```

**Python**

```python
import json

import requests

url = "{aiUrls}/ai/openapi/v2/instance-service/task"

payload = json.dumps({
    "instanceServiceName": "Instances_2205113838",
    "description": "",
    "taskType": "ssh",
    "acceleratorType": "gpu",
    "version": "jupyter:4.4-py3.7-cpu",
    "imagePath": "10.0.35.26:5000/gpu/admin/base/jupyter:4.4-py3.7-cpu",
    "timeoutLimit": "unlimited",
    "taskNumber": 1,
    "resourceGroup": "TeslaM40",
    "useStartScript": False,
    "startScriptActionScope": "all",
    "startScriptContent": "",
    "cpuNumber": 3,
    "ramSize": 15360,
    "gpuNumber": 1,
    "mountInfoList": [
        {
            "sourcePath": "/public1/home/lizb0530d/test_mount",
            "targetPath": "/mnt/test_mount",
            "type": "data",
        }
    ],
    "containerPortInfoList": [
        {
            "protocolType": "HTTP",
            "containerPort": "18888",
        }
    ],
})
headers = {
    "token": "<Token>",
    "Content-Type": "application/json",
}

response = requests.post(url, headers=headers, data=payload)
print(response.text)
```

**Java（OkHttp）**

```java
import okhttp3.*;

public class CreateContainerDemo {

    public static final String TOKEN = "<Token>";

    public static final String URL = "{aiUrls}/ai/openapi/v2/instance-service/task";

    public static void main(String[] args) throws Exception {
        OkHttpClient client = new OkHttpClient().newBuilder()
                .build();
        MediaType mediaType = MediaType.parse("application/json");
        RequestBody body = RequestBody.create(mediaType, "{\n    \"instanceServiceName\": \"Instances_2205113838\",\n    \"description\": \"\",\n    \"taskType\": \"ssh\",\n    \"acceleratorType\": \"gpu\",\n    \"version\": \"jupyter:4.4-py3.7-cpu\",\n    \"imagePath\": \"10.0.35.26:5000/gpu/admin/base/jupyter:4.4-py3.7-cpu\",\n    \"timeoutLimit\": \"unlimited\",\n    \"taskNumber\": 1,\n    \"resourceGroup\": \"TeslaM40\",\n    \"useStartScript\": false,\n    \"startScriptActionScope\": \"all\",\n    \"startScriptContent\": \"\",\n    \"cpuNumber\": 3,\n    \"ramSize\": 15360,\n    \"gpuNumber\": 1,\n    \"mountInfoList\": [\n            {\n                \"sourcePath\": \"/public1/home/lizb0530d/test_mount\",\n                \"targetPath\": \"/mnt/test_mount\",\n                \"type\": \"data\"\n            }\n        ],\n    \"containerPortInfoList\": [\n        {\n            \"protocolType\": \"HTTP\",\n            \"containerPort\": \"18888\"\n        }\n    ]\n}");
        Request request = new Request.Builder()
                .url(URL)
                .method("POST", body)
                .addHeader("token", TOKEN)
                .addHeader("Content-Type", "application/json")
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
| `msg` | string | 信息 | `操作成功` |
| `code` | string | 状态码 | `0` |
| `data` | string | **任务 ID（容器实例 ID）** | `530491fa7c8e47348f01de73e627a6a7` |

### 2. 返回示例

```json
{
  "code": "0",
  "msg": "success",
  "data": "530491fa7c8e47348f01de73e627a6a7"
}
```

> `data` 即容器实例 ID，后续「批量执行脚本」「查询实例详情」「批量删除容器」均使用该 ID。

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
| 716865 | 创建任务错误 |

---

## 五、要点提示

1. **认证方式**：通过请求头 `token` 传递凭证，非 `Authorization`。
2. **必填字段**：`acceleratorType`、`cpuNumber`、`gpuNumber`、`imagePath`、`instanceServiceName`、`ramSize`、`resourceGroup`、`startScriptActionScope`、`taskNumber`、`taskType`、`timeoutLimit`、`useStartScript`、`version`。
3. **条件必填**：`startScriptContent` 仅在 `useStartScript` 为 `true` 时必填；多行命令需以 `\n` 转义换行。
4. **挂载 `type`** 取值范围：`data` | `path`。
5. **端口协议 `protocolType`** 取值范围：`SSH` | `HTTP`。
6. **接口地址**：`{aiUrls}` 为占位符，需替换为「获取授权区域」返回的实际容器服务地址。
7. 创建成功后容器状态需通过「查询容器实例详情」确认（`data.status`）。
