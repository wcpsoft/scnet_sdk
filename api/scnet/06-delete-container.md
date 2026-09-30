# 批量删除容器

---

## 一、接口说明

| 项目 | 内容 |
|---|---|
| 接口路径 | `{aiUrls}/ai/openapi/v2/instance-service/task` |
| 请求方式 | `DELETE` |
| 请求数据类型 | （官方文档未填写） |
| 接口描述 | 批量删除容器 |

---

## 二、请求消息

### 1. 请求头

| 名称 | 类型 | 必填 | 描述 | 示例 |
|---|---|---|---|---|
| `token` | string | 是 | 接口凭证 | `eyJhbGciOiJIUzI1...` |

### 2. 请求参数（Query）

| 名称 | 类型 | 必填 | 描述 | 示例 |
|---|---|---|---|---|
| `ids` | array | 是 | 容器实例 ID 集合 | `ids=1bc50ecb6bc742a5afc0a8810018cb02&ids=195d453c7a424b32ac8593512fec6a26` |

> `ids` 为数组，通过**重复同名参数**传递，如 `?ids=xxx&ids=yyy`。

### 3. 完整请求地址

```
{aiUrls}/ai/openapi/v2/instance-service/task?ids=d3e0702e9389426cbc9cb86cdc548a54&ids=765aa93507c74b9eaee044cbaa51ed43
```

### 4. 请求示例

**cURL**

```shell
curl --location --request DELETE '{aiUrls}/ai/openapi/v2/instance-service/task?ids=d3e0702e9389426cbc9cb86cdc548a54&ids=765aa93507c74b9eaee044cbaa51ed43' \
--header 'token: <Token>'
```

**Python**

```python
import requests

url = "{aiUrls}/ai/openapi/v2/instance-service/task?ids=d3e0702e9389426cbc9cb86cdc548a54&ids=765aa93507c74b9eaee044cbaa51ed43"
headers = {"token": "<Token>"}

response = requests.request("DELETE", url, headers=headers)
print(response.text)
```

**Java（OkHttp）**

```java
import okhttp3.*;

public class BatchDeleteContainersDemo {

    public static final String TOKEN = "<Token>";

    public static void main(String[] args) throws Exception {
        OkHttpClient client = new OkHttpClient().newBuilder()
                .build();
        MediaType mediaType = MediaType.parse("text/plain");
        RequestBody body = RequestBody.create(mediaType, "");
        Request request = new Request.Builder()
                .url("{aiUrls}/ai/openapi/v2/instance-service/task?ids=d3e0702e9389426cbc9cb86cdc548a54&ids=765aa93507c74b9eaee044cbaa51ed43")
                .method("DELETE", body)
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
| `msg` | string | 信息 | `操作成功` |
| `code` | string | 状态码 | `0` |
| `data` | string | 返回值 | — |

### 2. 返回示例

```json
{
  "code": "0",
  "msg": "success",
  "data": null
}
```

> 官方文档中返回参数表 `msg` 示例为 `操作成功`，而返回示例中 `msg` 为 `"success"`，此处按文档原样保留。

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
| 716866 | 删除任务失败 |

---

## 五、要点提示

1. 请求方法为 `DELETE`，鉴权信息放在请求头 `token` 中。
2. 容器实例 ID 以重复的 `ids` 查询参数传入，**必填**。
3. 成功时 `code` 为 `"0"`，`data` 为 `null`；失败可通过错误码定位（如 `716866` 删除任务失败、`716020` 查询数据库错误）。
