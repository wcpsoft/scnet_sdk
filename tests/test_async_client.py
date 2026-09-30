"""AsyncScnetClient 单元测试：httpx.AsyncClient + MockTransport，不发起真实网络请求。

运行：
    python -m unittest discover -s tests -t . -v
    python tests/test_async_client.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

import httpx

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scnet_sdk import (  # noqa: E402
    AsyncScnetClient,
    ContainerSpec,
    MountInfo,
    PortInfo,
    ScnetApiError,
    ScnetClient,
    ScnetConfig,
    ScnetConfigError,
    ScnetStateError,
    ScnetTimeoutError,
    ScnetValidationError,
    build_signature,
    fetch_tokens_async,
    obtain_credentials_async,
)

AI_URL = 'https://hpc.example.com/ai'
CID = '530491fa7c8e47348f01de73e627a6a7'


def ok(data):
    return httpx.Response(200, json={'code': '0', 'msg': 'success', 'data': data})


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


class AsyncClientTestCase(unittest.IsolatedAsyncioTestCase):
    """统一的异步用例基类：注册并关闭测试用 AsyncClient。"""

    async def asyncSetUp(self):
        self._http_clients = []

    async def asyncTearDown(self):
        for http in self._http_clients:
            await http.aclose()

    def build(self, handler, **kwargs):
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self._http_clients.append(http)
        return AsyncScnetClient(
            token='token-abc',
            ai_url=AI_URL,
            http_client=http,
            search_user_config=False,
            use_environment=False,
            **kwargs,
        )


class AsyncAuthTests(AsyncClientTestCase):
    async def test_fetch_tokens_async_sends_signature_headers(self):
        seen = {}

        async def handler(request):
            seen['url'] = str(request.url)
            seen['headers'] = dict(request.headers)
            return ok([{'clusterId': '11112', 'clusterName': 'c', 'token': 'tk'}])

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self._http_clients.append(http)
        tokens = await fetch_tokens_async(
            'test', 'AK', 'SK', timestamp='1764597591', client=http
        )

        self.assertEqual(seen['url'], 'https://api.scnet.cn/api/user/v3/tokens')
        self.assertEqual(seen['headers']['user'], 'test')
        self.assertEqual(seen['headers']['accesskey'], 'AK')
        self.assertEqual(
            seen['headers']['signature'],
            build_signature('test', 'AK', 'SK', '1764597591'),
        )
        self.assertEqual(tokens[0].cluster_id, '11112')

    async def test_obtain_credentials_async(self):
        async def handler(request):
            if request.url.host == 'api.scnet.cn':
                return ok([{'clusterId': '11112', 'clusterName': 'c', 'token': 'tk'}])
            return ok({
                'id': 11112,
                'aiUrls': [
                    {'enable': 'false', 'url': 'https://bad.example.com/ai'},
                    {'enable': 'true', 'url': 'https://hpc.example.com/ai'},
                ],
            })

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self._http_clients.append(http)
        creds = await obtain_credentials_async('test', 'AK', 'SK', client=http)
        self.assertEqual(creds.token, 'tk')
        self.assertEqual(creds.ai_url, 'https://hpc.example.com/ai')

    async def test_from_credentials_async(self):
        calls = []

        async def handler(request):
            calls.append(request.url.host)
            if request.url.host == 'api.scnet.cn':
                return ok([{'clusterId': '11112', 'clusterName': 'c', 'token': 'tk-1'}])
            return ok({
                'id': 11112,
                'aiUrls': [{'enable': 'true', 'url': 'https://hpc.example.com/ai'}],
            })

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self._http_clients.append(http)
        client = await AsyncScnetClient.from_credentials(
            'test',
            'AK',
            'SK',
            search_user_config=False,
            use_environment=False,
            http_client=http,
        )
        self.assertEqual(client.token, 'tk-1')
        self.assertEqual(client.ai_url, 'https://hpc.example.com/ai')
        self.assertEqual(calls, ['api.scnet.cn', 'www.scnet.cn'])


class AsyncContainerTests(AsyncClientTestCase):
    async def test_create_container(self):
        seen = {}

        async def handler(request):
            seen['url'] = str(request.url)
            seen['method'] = request.method
            seen['token'] = request.headers.get('token')
            seen['body'] = json.loads(request.content.decode('utf-8'))
            return ok(CID)

        client = self.build(handler)
        container_id = await client.create_container(make_spec(ports=[PortInfo(18888)]))

        self.assertEqual(container_id, CID)
        self.assertEqual(seen['method'], 'POST')
        self.assertEqual(seen['url'], f'{AI_URL}/openapi/v2/instance-service/task')
        self.assertEqual(seen['token'], 'token-abc')
        self.assertEqual(seen['body']['instanceServiceName'], 'Instances_2205113838')
        self.assertEqual(
            seen['body']['containerPortInfoList'],
            [{'protocolType': 'HTTP', 'containerPort': '18888'}],
        )

    async def test_get_container_status(self):
        async def handler(request):
            self.assertEqual(
                request.url.path, f'/ai/openapi/v2/instance-service/{CID}/detail'
            )
            return ok({'id': CID, 'status': 'Waiting', 'duration': '--'})

        client = self.build(handler)
        info = await client.get_container_status(CID)
        self.assertEqual(info.status, 'Waiting')
        self.assertFalse(info.is_running)
        self.assertEqual(info.duration, '--')

    async def test_wait_for_container_until_running(self):
        states = ['Waiting', 'Waiting', 'Running']
        counter = {'n': 0}

        async def handler(request):
            index = min(counter['n'], len(states) - 1)
            counter['n'] += 1
            return ok({'id': CID, 'status': states[index]})

        client = self.build(handler)
        info = await client.wait_for_container(CID, poll_interval=0, timeout=5)
        self.assertTrue(info.is_running)
        self.assertEqual(counter['n'], 3)

    async def test_wait_for_container_async_poll_callback(self):
        seen = []

        async def handler(request):
            return ok({'id': CID, 'status': 'Running'})

        async def on_poll(attempt, info):
            await asyncio.sleep(0)
            seen.append((attempt, info.status))

        client = self.build(handler)
        await client.wait_for_container(CID, poll_interval=0, on_poll=on_poll)
        self.assertEqual(seen, [(1, 'Running')])

    async def test_wait_for_container_terminal_and_timeout(self):
        async def terminal_handler(request):
            return ok({'id': CID, 'status': 'Failed'})

        client = self.build(terminal_handler)
        with self.assertRaises(ScnetStateError):
            await client.wait_for_container(CID, poll_interval=0, timeout=5)

        async def pending_handler(request):
            return ok({'id': CID, 'status': 'Waiting'})

        client = self.build(pending_handler)
        with self.assertRaises(ScnetTimeoutError):
            await client.wait_for_container(CID, poll_interval=0.01, timeout=0.05)

    async def test_custom_running_statuses(self):
        async def handler(request):
            return ok({'id': CID, 'status': 'DEPLOY'})

        client = self.build(handler, running_statuses=('deploy',))
        info = await client.wait_for_container(CID, poll_interval=0)
        self.assertTrue(info.is_running_with(('deploy',)))

    async def test_execute_script(self):
        seen = {}

        async def handler(request):
            seen['url'] = str(request.url)
            seen['body'] = json.loads(request.content.decode('utf-8'))
            return ok(None)

        client = self.build(handler)
        await client.execute_script(CID, 'echo "hello world"\necho done\n', scope='header')

        self.assertEqual(
            seen['url'], f'{AI_URL}/openapi/v2/instance-service/task/actions/execute-script'
        )
        self.assertEqual(seen['body'], {
            'startScriptActionScope': 'header',
            'startScriptContent': 'echo "hello world"\necho done\n',
            'id': CID,
        })

    async def test_execute_script_rejects_bad_scope(self):
        client = self.build(lambda request: ok(None))
        with self.assertRaises(ScnetValidationError):
            await client.execute_script(CID, 'echo hi', scope='first')
        with self.assertRaises(ScnetValidationError):
            await client.execute_script('', 'echo hi')

    async def test_delete_containers_repeats_ids(self):
        seen = {}

        async def handler(request):
            seen['method'] = request.method
            seen['path'] = request.url.path
            seen['ids'] = request.url.params.get_list('ids')
            return ok(None)

        client = self.build(handler)
        await client.delete_containers(['id-1', 'id-2'])

        self.assertEqual(seen['method'], 'DELETE')
        self.assertEqual(seen['path'], '/ai/openapi/v2/instance-service/task')
        self.assertEqual(seen['ids'], ['id-1', 'id-2'])

    async def test_resource_limits(self):
        async def handler(request):
            self.assertEqual(request.url.params['resourceGroup'], 'TeslaM40')
            self.assertEqual(request.url.params['acceleratorType'], 'gpu')
            return ok({
                'cpuNumber': 40, 'gpuNumber': 2, 'memorySize': 31888,
                'resourceGroup': 'TeslaM40', 'nodeNumber': 1, 'maxTime': 'unlimited',
            })

        client = self.build(handler)
        limits = await client.resource_limits('TeslaM40', 'GPU')
        self.assertEqual(limits.cpu_number, 40)
        self.assertEqual(limits.memory_size, 31888)


class AsyncLifecycleTests(AsyncClientTestCase):
    async def test_open_container_creates_waits_and_deletes(self):
        calls = []

        async def handler(request):
            if request.method == 'POST':
                calls.append('create')
                return ok(CID)
            if request.method == 'DELETE':
                calls.append('delete')
                self.assertEqual(request.url.params.get_list('ids'), [CID])
                return ok(None)
            calls.append('detail')
            return ok({'id': CID, 'status': 'Running'})

        client = self.build(handler)
        async with client.open_container(make_spec(), poll_interval=0, wait_timeout=5) as handle:
            self.assertEqual(handle.id, CID)
            self.assertEqual(await handle.status(), 'Running')
            self.assertEqual(
                await handle.info(), await client.get_container(CID)
            )

        # create -> wait 时查一次 -> handle.status() -> handle.info() -> 断言里再查一次 -> delete
        self.assertEqual(calls, ['create', 'detail', 'detail', 'detail', 'detail', 'delete'])

    async def test_open_container_keep_flag_and_execute(self):
        calls = []

        async def handler(request):
            path = request.url.path
            if path.endswith('/task') and request.method == 'POST':
                calls.append('create')
                return ok(CID)
            if path.endswith('/execute-script'):
                calls.append('execute')
                return ok(None)
            if request.method == 'DELETE':
                calls.append('delete')
                return ok(None)
            return ok({'id': CID, 'status': 'Running'})

        client = self.build(handler)
        async with client.open_container(make_spec(), wait=False, keep=True) as handle:
            await handle.execute('echo hi')
        self.assertEqual(calls, ['create', 'execute'])


class AsyncConfigTests(AsyncClientTestCase):
    async def test_aclose_owned_client(self):
        client = AsyncScnetClient(
            token='tk',
            ai_url=AI_URL,
            search_user_config=False,
            use_environment=False,
        )
        await client.aclose()

    async def test_async_context_manager(self):
        async def handler(request):
            return ok({'id': CID, 'status': 'Running'})

        client = self.build(handler)
        async with client as entered:
            self.assertIs(entered, client)

    async def test_lazy_ai_url_resolution(self):
        seen = []

        async def handler(request):
            seen.append(str(request.url))
            if request.url.host == 'www.scnet.cn':
                return ok({
                    'id': 11112,
                    'aiUrls': [{'enable': 'true', 'url': 'https://hpc.example.com/ai'}],
                })
            return ok({'id': CID, 'status': 'Running'})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self._http_clients.append(http)
        client = AsyncScnetClient(
            token='tk',
            http_client=http,
            search_user_config=False,
            use_environment=False,
        )
        self.assertIsNone(client.ai_url)
        info = await client.get_container(CID)
        self.assertEqual(info.status, 'Running')
        self.assertEqual(client.ai_url, 'https://hpc.example.com/ai')
        self.assertEqual(
            seen,
            [
                'https://www.scnet.cn/ac/openapi/v2/center',
                f'{AI_URL}/openapi/v2/instance-service/{CID}/detail',
            ],
        )

    async def test_config_driven_paths_and_timeouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / 'scnet.yaml'
            config_file.write_text(
                'paths:\n'
                '  task: /custom/task\n'
                '  detail: /custom/{container_id}/detail\n'
                'timeouts:\n'
                '  wait: 0.05\n'
                '  poll_interval: 0.01\n',
                encoding='utf-8',
            )
            seen = []

            async def handler(request):
                seen.append(request.url.path)
                if request.method == 'POST':
                    return ok('cid-1')
                return ok({'id': 'cid-1', 'status': 'Waiting'})

            http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            self._http_clients.append(http)
            client = await AsyncScnetClient.from_config(
                str(config_file),
                http_client=http,
                token='tk',
                ai_url=AI_URL,
                env={},
                use_environment=False,
            )
            self.assertEqual(await client.create_container(make_spec()), 'cid-1')
            with self.assertRaises(ScnetTimeoutError):
                await client.wait_for_container('cid-1')

        self.assertIn('/ai/custom/task', seen)
        self.assertIn('/ai/custom/cid-1/detail', seen)


class AsyncErrorTests(AsyncClientTestCase):
    async def test_api_error_code(self):
        async def handler(request):
            return httpx.Response(
                200, json={'code': '716865', 'msg': '创建任务错误', 'data': None}
            )

        client = self.build(handler)
        with self.assertRaises(ScnetApiError) as ctx:
            await client.create_container(make_spec())
        self.assertEqual(ctx.exception.code, '716865')

    async def test_missing_token(self):
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: ok(None)))
        self._http_clients.append(http)
        client = AsyncScnetClient(
            ai_url=AI_URL,
            http_client=http,
            search_user_config=False,
            use_environment=False,
        )
        with self.assertRaises(ScnetConfigError):
            await client.create_container(make_spec())

    async def test_from_config_requires_credentials(self):
        config = ScnetConfig.load(env={}, search_user_config=False, use_environment=False)
        with self.assertRaises(ScnetConfigError):
            await AsyncScnetClient.from_config(config=config)

    async def test_transport_error_is_wrapped(self):
        async def handler(request):
            raise httpx.ConnectError('boom', request=request)

        client = self.build(handler)
        with self.assertRaises(Exception) as ctx:
            await client.get_container(CID)
        self.assertIn('请求失败', str(ctx.exception))


class SyncAsyncParityTests(AsyncClientTestCase):
    """同一 spec 下，同步与异步客户端发出的请求必须完全一致。"""

    async def test_create_payload_parity(self):
        bodies = []

        spec = make_spec(
            mounts=[MountInfo('/public1/home/u/m', '/mnt/m', 'data')],
            ports=[PortInfo(18888, 'HTTP')],
            description='parity',
            use_start_script=True,
            start_script_content='echo a\necho b\n',
        )

        sync_bodies = []

        def sync_handler(request):
            sync_bodies.append(json.loads(request.content.decode('utf-8')))
            return ok(CID)

        async def async_handler(request):
            bodies.append(json.loads(request.content.decode('utf-8')))
            return ok(CID)

        sync_client = ScnetClient(
            token='token-abc',
            ai_url=AI_URL,
            http_client=httpx.Client(transport=httpx.MockTransport(sync_handler)),
            search_user_config=False,
            use_environment=False,
        )
        self.assertEqual(sync_client.create_container(spec), CID)

        async_client = self.build(async_handler)
        self.assertEqual(await async_client.create_container(spec), CID)

        self.assertEqual(len(sync_bodies), 1)
        self.assertEqual(sync_bodies, bodies)


if __name__ == '__main__':
    unittest.main()
