# 批量执行脚本

向已创建的容器实例批量下发并执行脚本。

---

## 一、接口说明

| 项目 | 内容 |
|---|---|
| 接口路径 | `{aiUrls}/ai/openapi/v2/instance-service/task/actions/execute-script` |
| 请求方式 | `POST` |
| 请求数据类型 | `application/json` |
| 接口描述 | 批量执行脚本 |

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
| `startScriptActionScope` | string | 是 | 批量执行脚本范围：`all`（代表所有容器）、`header`（代表首个容器） | `all` |
| `startScriptContent` | string | 是 | 批量执行脚本的内容；多行命令时需在每行末尾加入 `\n` 换行转义符 | `echo \"hello world\"` |
| `id` | string | 是 | 容器实例 ID | `7d64e73803de4a6e9a15a8c79c7da015` |

### 3. 请求示例

**cURL**

```shell
curl --location '{aiUrls}/ai/openapi/v2/instance-service/task/actions/execute-script' \
--header 'token: <Token>' \
--header 'Content-Type: application/json' \
--data '{
  "startScriptActionScope": "all",
  "startScriptContent": "echo \"hello world\"",
  "id": "7d64e73803de4a6e9a15a8c79c7da015"
}'
```

**Python**

```python
import json

import requests

url = "{aiUrls}/ai/openapi/v2/instance-service/task/actions/execute-script"
payload = json.dumps({
    "startScriptActionScope": "all",
    "startScriptContent": "echo \"hello world\"",
    "id": "7d64e73803de4a6e9a15a8c79c7da015",
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

public class BatchExecuteScriptDemo {

    public static final String TOKEN = "<Token>";

    public static final String URL = "{aiUrls}/ai/openapi/v2/instance-service/task/actions/execute-script";

    public static void main(String[] args) throws Exception {
        OkHttpClient client = new OkHttpClient().newBuilder()
                .build();
        MediaType mediaType = MediaType.parse("application/json");
        RequestBody body = RequestBody.create(mediaType, "{\n    \"startScriptActionScope\": \"all\",\n    \"startScriptContent\": \"echo \\\"hello world\\\"\",\n    \"id\": \"7d64e73803de4a6e9a15a8c79c7da015\"\n}");
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
| `data` | string | 返回值 | `null` |

### 2. 返回示例

```json
{
  "code": "0",
  "msg": "success",
  "data": null
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
| 716020 | 查询数据库错误 |
| 716864 | 执行脚本错误 |
| 716870 | 实例数量错误 |

---

## 五、要点提示

- `startScriptContent` 中多行命令需在**每行末尾**添加 `\n` 换行转义符。
- `startScriptActionScope` 官方原文为 `all`（所有容器）/ `header`（首个容器）；实际调用前建议确认取值。
- 本接口为**异步下发**，返回 `code` 为 `0` 仅代表下发成功，实际执行结果请在容器内查看输出，或通过「查询容器实例详情」确认实例状态。
- 该接口文档页面中**不包含**「查询容器执行状态」接口，执行状态请使用 [`05-container-status.md`](./05-container-status.md)。
