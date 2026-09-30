"""scnet_sdk 单元测试：全部使用 httpx.MockTransport，不发起真实网络请求。

运行：
    python -m unittest discover -s tests -t . -v
    python tests/test_scnet_sdk.py -v
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import unittest
from pathlib import Path

import httpx

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scnet_sdk import (  # noqa: E402
    ContainerInfo,
    ContainerSpec,
    MountInfo,
    PortInfo,
    ScnetApiError,
    ScnetAuthError,
    ScnetClient,
    ScnetConfigError,
    ScnetResponseError,
    ScnetStateError,
    ScnetTimeoutError,
    ScnetValidationError,
    build_sign_message,
    build_signature,
    fetch_tokens,
    join_script_lines,
    normalize_ai_url,
    obtain_credentials,
    pick_ai_urls,
    resolve_ai_url,
    select_cluster,
)
from scnet_sdk.auth import ClusterToken  # noqa: E402

AI_URL = 'https://hpc.example.com/ai'
CONTAINER_ID = '530491fa7c8e47348f01de73e627a6a7'


def ok(data):
    return httpx.Response(200, json={'code': '0', 'msg': 'success', 'data': data})


def make_client(handler, **kwargs):
    """构造测试客户端：关闭用户态文件搜索与环境变量，避免依赖本机状态。"""
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return ScnetClient(
        token='token-abc',
        ai_url=AI_URL,
        http_client=http,
        search_user_config=False,
        use_environment=False,
        **kwargs,
    )


def make_spec(**overrides):
    params = {
        'instance_service_name': 'Instances_2205113838',
        'image_path': '10.0.35.26:5000/gpu/admin/base/jupyter:4.4-py3.7-cpu',
        'version': 'jupyter:4.4-py3.7-cpu',
        'resource_group': 'TeslaM40',
        'accelerator_type': 'gpu',
        'cpu_number': 3,
        'ram_size': 15360,
        'gpu_number': 1,
    }
    params.update(overrides)
    return ContainerSpec(**params)


class SignatureTests(unittest.TestCase):
    def test_sign_message_is_compact_and_ordered(self):
        message = build_sign_message('bob', 'AK1', '1764597591')
        self.assertEqual(
            message, '{"accessKey":"AK1","timestamp":"1764597591","user":"bob"}'
        )

    def test_signature_matches_manual_hmac_sha256(self):
        message = build_sign_message('bob', 'AK1', '1764597591')
        expected = hmac.new(b'SK1', message.encode('utf-8'), hashlib.sha256).hexdigest()
        self.assertEqual(build_signature('bob', 'AK1', 'SK1', '1764597591'), expected)


class AuthFlowTests(unittest.TestCase):
    def test_fetch_tokens_uses_ak_headers(self):
        seen = {}

        def handler(request):
            seen['url'] = str(request.url)
            seen['headers'] = dict(request.headers)
            return ok([
                {'clusterId': '11112', 'clusterName': 'OpenAPI计算中心', 'token': 'tk-11112'},
                {'clusterId': '0', 'clusterName': 'ac', 'token': 'tk-ac'},
            ])

        http = httpx.Client(transport=httpx.MockTransport(handler))
        tokens = fetch_tokens('test', 'AK', 'SK', timestamp='1764597591', client=http)

        self.assertEqual(seen['url'], 'https://api.scnet.cn/api/user/v3/tokens')
        self.assertEqual(seen['headers']['user'], 'test')
        self.assertEqual(seen['headers']['accesskey'], 'AK')
        self.assertEqual(seen['headers']['timestamp'], '1764597591')
        self.assertEqual(
            seen['headers']['signature'], build_signature('test', 'AK', 'SK', '1764597591')
        )
        self.assertEqual([item.cluster_id for item in tokens], ['11112', '0'])
        self.assertTrue(tokens[0].usable)

    def test_select_cluster_skips_platform_and_null_tokens(self):
        tokens = (
            ClusterToken('0', 'ac', 'tk-ac'),
            ClusterToken('111131', 'test中心', None),
            ClusterToken('11112', 'OpenAPI计算中心', 'tk-11112'),
        )
        self.assertEqual(select_cluster(tokens).cluster_id, '11112')
        with self.assertRaises(ScnetAuthError):
            select_cluster(tokens, '111131')
        with self.assertRaises(ScnetAuthError):
            select_cluster(tokens, '99999')

    def test_obtain_credentials_resolves_ai_url(self):
        def handler(request):
            if request.url.host == 'api.scnet.cn':
                return ok([{'clusterId': '11112', 'clusterName': 'c', 'token': 'tk'}])
            return ok({
                'id': 11112,
                'aiUrls': [
                    {'enable': 'false', 'url': 'https://bad.example.com/ai'},
                    {'enable': 'true', 'url': 'https://hpc.example.com/ai'},
                ],
            })

        http = httpx.Client(transport=httpx.MockTransport(handler))
        creds = obtain_credentials('test', 'AK', 'SK', client=http)
        self.assertEqual(creds.token, 'tk')
        self.assertEqual(creds.cluster_id, '11112')
        self.assertEqual(creds.ai_url, 'https://hpc.example.com/ai')


class AiUrlTests(unittest.TestCase):
    def test_normalize_appends_ai_suffix(self):
        self.assertEqual(normalize_ai_url('https://host'), 'https://host/ai')
        self.assertEqual(normalize_ai_url('https://host/ai/'), 'https://host/ai')

    def test_resolve_ai_url_handles_string_and_placeholder(self):
        self.assertEqual(resolve_ai_url({'aiUrls': 'https://host/ai'}), 'https://host/ai')
        self.assertEqual(
            resolve_ai_url({'aiUrls': [{'enable': 'true', 'url': 'https://host/ai'}]}),
            'https://host/ai',
        )
        with self.assertRaises(ScnetConfigError):
            resolve_ai_url({'aiUrls': [{'enable': 'true', 'url': '{hpcUrls}/ai'}]})

    def test_pick_ai_urls_falls_back_when_none_enabled(self):
        self.assertEqual(
            pick_ai_urls({'aiUrls': [{'enable': 'false', 'url': 'https://host/ai'}]}),
            ('https://host/ai',),
        )


class ModelTests(unittest.TestCase):
    def test_spec_payload_matches_documented_fields(self):
        spec = make_spec(
            mounts=[MountInfo('/public1/home/u/test_mount', '/mnt/test_mount', 'data')],
            ports=[PortInfo(18888, 'HTTP')],
            description='',
        )
        payload = spec.to_payload()
        self.assertEqual(payload['instanceServiceName'], 'Instances_2205113838')
        self.assertEqual(payload['acceleratorType'], 'gpu')
        self.assertEqual(payload['taskType'], 'ssh')
        self.assertEqual(payload['timeoutLimit'], 'unlimited')
        self.assertEqual(payload['taskNumber'], 1)
        self.assertFalse(payload['useStartScript'])
        self.assertEqual(payload['startScriptActionScope'], 'all')
        self.assertEqual(payload['cpuNumber'], 3)
        self.assertEqual(payload['ramSize'], 15360)
        self.assertEqual(payload['gpuNumber'], 1)
        self.assertEqual(
            payload['mountInfoList'],
            [{
                'sourcePath': '/public1/home/u/test_mount',
                'targetPath': '/mnt/test_mount',
                'type': 'data',
            }],
        )
        self.assertEqual(
            payload['containerPortInfoList'],
            [{'protocolType': 'HTTP', 'containerPort': '18888'}],
        )

    def test_spec_omits_optional_lists_when_empty(self):
        payload = make_spec().to_payload()
        self.assertNotIn('mountInfoList', payload)
        self.assertNotIn('containerPortInfoList', payload)

    def test_spec_validation_errors(self):
        with self.assertRaises(ScnetValidationError):
            make_spec(accelerator_type='tpu')
        with self.assertRaises(ScnetValidationError):
            make_spec(task_type='notebook')
        with self.assertRaises(ScnetValidationError):
            make_spec(cpu_number=0)
        with self.assertRaises(ScnetValidationError):
            make_spec(use_start_script=True)
        with self.assertRaises(ScnetValidationError):
            make_spec(ports=[PortInfo(18888, 'TCP')])
        with self.assertRaises(ScnetValidationError):
            make_spec(mounts=[MountInfo('/a', '/b', 'volume')])
        with self.assertRaises(ScnetValidationError):
            ContainerSpec(
                instance_service_name='', image_path='i', version='v', resource_group='g'
            )

    def test_spec_extra_fields_are_merged(self):
        payload = make_spec(extra={'startScriptPath': '/public/home/u/run.sh'}).to_payload()
        self.assertEqual(payload['startScriptPath'], '/public/home/u/run.sh')

    def test_port_int_mode(self):
        self.assertEqual(
            PortInfo(18888, 'http', as_string=False).to_dict(),
            {'protocolType': 'HTTP', 'containerPort': 18888},
        )

    def test_join_script_lines(self):
        self.assertEqual(join_script_lines(['echo a', '', 'echo b']), 'echo a\necho b\n')

    def test_container_info_status_helpers(self):
        running = ContainerInfo.from_dict({
            'id': 'x',
            'status': 'Running',
            'containerPortInfoList': [
                {'accessUrl': 'https://jupyter.example.com', 'containerPort': '18888'}
            ],
        })
        self.assertTrue(running.is_running)
        self.assertFalse(running.is_terminal)
        self.assertEqual(running.access_urls, ('https://jupyter.example.com',))

        waiting = ContainerInfo.from_dict({'id': 'x', 'status': 'Waiting'})
        self.assertFalse(waiting.is_running)
        self.assertFalse(waiting.is_terminal)

        failed = ContainerInfo.from_dict({'id': 'x', 'status': 'Failed'})
        self.assertTrue(failed.is_terminal)


class CreateContainerTests(unittest.TestCase):
    def test_create_container_returns_id(self):
        seen = {}

        def handler(request):
            seen['url'] = str(request.url)
            seen['method'] = request.method
            seen['token'] = request.headers.get('token')
            seen['body'] = json.loads(request.content.decode('utf-8'))
            return ok(CONTAINER_ID)

        client = make_client(handler)
        container_id = client.create_container(make_spec(ports=[PortInfo(18888)]))

        self.assertEqual(container_id, CONTAINER_ID)
        self.assertEqual(seen['method'], 'POST')
        self.assertEqual(seen['url'], f'{AI_URL}/openapi/v2/instance-service/task')
        self.assertEqual(seen['token'], 'token-abc')
        self.assertEqual(seen['body']['instanceServiceName'], 'Instances_2205113838')

    def test_create_container_surfaces_api_error_code(self):
        def handler(request):
            return httpx.Response(
                200, json={'code': '716865', 'msg': '创建任务错误', 'data': None}
            )

        client = make_client(handler)
        with self.assertRaises(ScnetApiError) as ctx:
            client.create_container(make_spec())
        self.assertEqual(ctx.exception.code, '716865')
        self.assertIn('创建任务错误', str(ctx.exception))

    def test_missing_token_raises_config_error(self):
        http = httpx.Client(transport=httpx.MockTransport(lambda request: ok(None)))
        client = ScnetClient(
            ai_url=AI_URL, http_client=http, search_user_config=False, use_environment=False
        )
        with self.assertRaises(ScnetConfigError):
            client.create_container(make_spec())


class StatusTests(unittest.TestCase):
    def test_get_container_detail(self):
        def handler(request):
            self.assertEqual(request.method, 'GET')
            self.assertEqual(
                request.url.path, f'/ai/openapi/v2/instance-service/{CONTAINER_ID}/detail'
            )
            return ok({
                'id': CONTAINER_ID,
                'status': 'Waiting',
                'resourceSpec': '3 核心; 1 加速器; 15.0G 内存',
                'createTime': '2022-05-11 19:30:34',
                'startTime': None,
                'duration': '--',
                'mountInfoList': [],
                'containerPortInfoList': [],
            })

        client = make_client(handler)
        info = client.get_container(CONTAINER_ID)
        self.assertEqual(info.id, CONTAINER_ID)
        self.assertEqual(info.status, 'Waiting')
        self.assertFalse(info.is_running)
        self.assertEqual(info.resource_spec, '3 核心; 1 加速器; 15.0G 内存')
        self.assertEqual(info.duration, '--')
        self.assertEqual(client.get_container_status(CONTAINER_ID).status, 'Waiting')

    def test_wait_for_container_until_running(self):
        states = ['Waiting', 'Waiting', 'Running']
        counter = {'n': 0}

        def handler(request):
            index = min(counter['n'], len(states) - 1)
            counter['n'] += 1
            return ok({'id': CONTAINER_ID, 'status': states[index]})

        client = make_client(handler)
        info = client.wait_for_container(CONTAINER_ID, poll_interval=0, timeout=5)
        self.assertTrue(info.is_running)
        self.assertEqual(counter['n'], 3)

    def test_wait_for_container_raises_on_terminal_status(self):
        client = make_client(lambda request: ok({'id': CONTAINER_ID, 'status': 'Failed'}))
        with self.assertRaises(ScnetStateError):
            client.wait_for_container(CONTAINER_ID, poll_interval=0, timeout=5)

    def test_wait_for_container_times_out(self):
        client = make_client(lambda request: ok({'id': CONTAINER_ID, 'status': 'Waiting'}))
        with self.assertRaises(ScnetTimeoutError):
            client.wait_for_container(CONTAINER_ID, poll_interval=0.01, timeout=0.05)

    def test_custom_running_statuses(self):
        client = make_client(
            lambda request: ok({'id': CONTAINER_ID, 'status': 'DEPLOY'}),
            running_statuses=('deploy',),
        )
        info = client.wait_for_container(CONTAINER_ID, poll_interval=0)
        self.assertTrue(info.is_running_with(('deploy',)))


class ScriptAndDeleteTests(unittest.TestCase):
    def test_execute_script_payload(self):
        seen = {}

        def handler(request):
            seen['url'] = str(request.url)
            seen['body'] = json.loads(request.content.decode('utf-8'))
            return ok(None)

        client = make_client(handler)
        client.execute_script(CONTAINER_ID, 'echo "hello world"\necho done\n', scope='header')

        self.assertEqual(
            seen['url'], f'{AI_URL}/openapi/v2/instance-service/task/actions/execute-script'
        )
        self.assertEqual(seen['body'], {
            'startScriptActionScope': 'header',
            'startScriptContent': 'echo "hello world"\necho done\n',
            'id': CONTAINER_ID,
        })

    def test_execute_script_rejects_bad_scope(self):
        client = make_client(lambda request: ok(None))
        with self.assertRaises(ScnetValidationError):
            client.execute_script(CONTAINER_ID, 'echo hi', scope='first')

    def test_delete_containers_repeats_ids_param(self):
        seen = {}

        def handler(request):
            seen['method'] = request.method
            seen['path'] = request.url.path
            seen['ids'] = request.url.params.get_list('ids')
            return ok(None)

        client = make_client(handler)
        client.delete_containers(['id-1', 'id-2'])

        self.assertEqual(seen['method'], 'DELETE')
        self.assertEqual(seen['path'], '/ai/openapi/v2/instance-service/task')
        self.assertEqual(seen['ids'], ['id-1', 'id-2'])

    def test_delete_container_single(self):
        seen = {}

        def handler(request):
            seen['ids'] = request.url.params.get_list('ids')
            return ok(None)

        client = make_client(handler)
        client.delete_container(CONTAINER_ID)
        self.assertEqual(seen['ids'], [CONTAINER_ID])

    def test_delete_rejects_empty_ids(self):
        client = make_client(lambda request: ok(None))
        with self.assertRaises(ScnetValidationError):
            client.delete_containers([])


class ResourceLimitsTests(unittest.TestCase):
    def test_resource_limits(self):
        def handler(request):
            self.assertEqual(request.url.params['resourceGroup'], 'TeslaM40')
            self.assertEqual(request.url.params['acceleratorType'], 'gpu')
            return ok({
                'id': None, 'cpuNumber': 40, 'mluLimits': 0, 'dcuLimits': 0, 'nvLimits': 0,
                'gpuNumber': 2, 'memorySize': 31888, 'resourceGroup': 'TeslaM40',
                'userName': None, 'nodeNumber': 1, 'maxTime': 'unlimited',
            })

        client = make_client(handler)
        limits = client.resource_limits('TeslaM40', 'GPU')
        self.assertEqual(limits.cpu_number, 40)
        self.assertEqual(limits.gpu_number, 2)
        self.assertEqual(limits.memory_size, 31888)
        self.assertEqual(limits.max_time, 'unlimited')


class LifecycleTests(unittest.TestCase):
    def test_open_container_creates_waits_and_deletes(self):
        calls = []

        def handler(request):
            path = request.url.path
            if request.method == 'POST':
                calls.append('create')
                return ok(CONTAINER_ID)
            if request.method == 'DELETE':
                calls.append('delete')
                self.assertEqual(request.url.params.get_list('ids'), [CONTAINER_ID])
                return ok(None)
            calls.append('detail')
            return ok({'id': CONTAINER_ID, 'status': 'Running'})

        client = make_client(handler)
        with client.open_container(make_spec(), poll_interval=0, wait_timeout=5) as container:
            self.assertEqual(container.id, CONTAINER_ID)
            self.assertEqual(container.status, 'Running')

        # create -> wait 时查一次 -> with 内读 status 再查一次 -> delete
        self.assertEqual(calls, ['create', 'detail', 'detail', 'delete'])

    def test_open_container_keep_flag(self):
        calls = []

        def handler(request):
            path = request.url.path
            if path.endswith('/task') and request.method == 'POST':
                calls.append('create')
                return ok(CONTAINER_ID)
            if path.endswith('/execute-script'):
                calls.append('execute')
                return ok(None)
            if request.method == 'DELETE':
                calls.append('delete')
                return ok(None)
            return ok({'id': CONTAINER_ID, 'status': 'Running'})

        client = make_client(handler)
        with client.open_container(make_spec(), wait=False, keep=True) as container:
            container.execute('echo hi')
        self.assertEqual(calls, ['create', 'execute'])


class ErrorHandlingTests(unittest.TestCase):
    def test_http_401_raises_auth_error(self):
        client = make_client(lambda request: httpx.Response(401, text='Unauthorized'))
        with self.assertRaises(ScnetAuthError):
            client.get_container(CONTAINER_ID)

    def test_non_json_response_raises_response_error(self):
        client = make_client(lambda request: httpx.Response(200, text='<html>oops</html>'))
        with self.assertRaises(ScnetResponseError):
            client.get_container(CONTAINER_ID)

    def test_api_error_carries_payload(self):
        def handler(request):
            return httpx.Response(200, json={'code': '10003', 'msg': '参数不全', 'data': None})

        client = make_client(handler)
        with self.assertRaises(ScnetApiError) as ctx:
            client.get_container(CONTAINER_ID)
        self.assertEqual(ctx.exception.code, '10003')
        self.assertEqual(ctx.exception.payload['msg'], '参数不全')


if __name__ == '__main__':
    unittest.main()
