"""配置系统（系统态 + 用户态）单元测试，不发起真实网络请求。

运行：
    python -m unittest discover -s tests -t . -v
    python tests/test_config.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import httpx

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scnet_sdk import (  # noqa: E402
    ScnetClient,
    ScnetConfig,
    ScnetConfigError,
    ScnetTimeoutError,
    deep_merge,
    load_yaml,
    packaged_defaults,
    resolve_config_path,
)

USER_YAML = """
cluster_id: "11112"
user: alice
access_key: AK-TEST
secret_key: SK-TEST
timeouts:
  poll_interval: 2.5
statuses:
  running:
    - running
    - deploying
"""


class TemporaryConfigMixin(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / 'home'
        self.work = self.tmp / 'work'
        self.home.mkdir(parents=True, exist_ok=True)
        self.work.mkdir(parents=True, exist_ok=True)
        self.env = {'HOME': str(self.home)}

    def write_user_config(self, text: str, name: str = 'scnet.yaml') -> Path:
        path = self.work / name
        path.write_text(text, encoding='utf-8')
        return path


class SystemDefaultsTests(unittest.TestCase):
    def test_packaged_defaults_match_documented_values(self):
        data = packaged_defaults()
        self.assertEqual(
            data['endpoints']['token_url'],
            'https://api.scnet.cn/api/user/v3/tokens',
        )
        self.assertEqual(data['endpoints']['center_url'], 'https://www.scnet.cn/ac/openapi/v2/center')
        self.assertEqual(data['paths']['task'], '/openapi/v2/instance-service/task')
        self.assertEqual(
            data['paths']['execute_script'],
            '/openapi/v2/instance-service/task/actions/execute-script',
        )
        self.assertEqual(
            data['paths']['detail'], '/openapi/v2/instance-service/{container_id}/detail'
        )
        self.assertIn('running', data['statuses'])
        self.assertIn('failed', data['statuses']['terminal'])

    def test_load_without_user_config_uses_system_defaults(self):
        config = ScnetConfig.load(env=self_env(), search_user_config=False, use_environment=False)
        self.assertEqual(config.endpoints.center_url, 'https://www.scnet.cn/ac/openapi/v2/center')
        self.assertEqual(config.timeouts.request, 30.0)
        self.assertEqual(config.timeouts.wait, 1800.0)
        self.assertEqual(config.timeouts.poll_interval, 5.0)
        self.assertEqual(config.statuses.running, ('running',))
        self.assertIsNone(config.token)
        self.assertEqual(config.paths.detail_for('abc'), '/openapi/v2/instance-service/abc/detail')


def self_env():
    return {'HOME': os.environ.get('HOME', '')}


class UserConfigTests(TemporaryConfigMixin):
    def test_user_yaml_overrides_and_deep_merges(self):
        path = self.write_user_config(USER_YAML)
        config = ScnetConfig.load(
            path, env=self.env, cwd=str(self.work), use_environment=False
        )
        # 用户态字段
        self.assertEqual(config.cluster_id, '11112')
        self.assertEqual(config.user, 'alice')
        self.assertEqual(config.access_key, 'AK-TEST')
        # 覆盖嵌套值
        self.assertEqual(config.timeouts.poll_interval, 2.5)
        # 深合并保留未覆盖的兄弟键
        self.assertEqual(config.timeouts.request, 30.0)
        self.assertEqual(config.statuses.running, ('running', 'deploying'))
        self.assertIn('failed', config.statuses.terminal)
        # 加载来源可诊断
        self.assertTrue(any('用户态' in item for item in config.sources))

    def test_default_search_finds_cwd_config(self):
        path = self.write_user_config(USER_YAML)
        config = ScnetConfig.load(env=self.env, cwd=str(self.work), use_environment=False)
        self.assertEqual(config.user, 'alice')
        self.assertIn(str(path), ' '.join(config.sources))

    def test_default_search_finds_home_config(self):
        target = self.home / '.config' / 'scnet'
        target.mkdir(parents=True)
        (target / 'scnet.yaml').write_text(USER_YAML, encoding='utf-8')
        config = ScnetConfig.load(env=self.env, cwd=str(self.work), use_environment=False)
        self.assertEqual(config.cluster_id, '11112')

    def test_env_var_points_to_config(self):
        path = self.write_user_config(USER_YAML, name='custom.yaml')
        config = ScnetConfig.load(
            env={'HOME': str(self.home), 'SCNET_CONFIG': str(path)},
            cwd=str(self.work),
            use_environment=False,
        )
        self.assertEqual(config.user, 'alice')

    def test_missing_explicit_path_raises(self):
        with self.assertRaises(ScnetConfigError):
            ScnetConfig.load(self.tmp / 'nope.yaml', env=self.env, use_environment=False)

    def test_missing_env_path_raises(self):
        with self.assertRaises(ScnetConfigError):
            ScnetConfig.load(env={'HOME': str(self.home), 'SCNET_CONFIG': str(self.tmp / 'nope.yaml')})

    def test_invalid_yaml_raises(self):
        path = self.write_user_config('user: [unclosed\n')
        with self.assertRaises(ScnetConfigError):
            load_yaml(path)

    def test_unknown_keys_raise(self):
        path = self.write_user_config('unknown_section: 1\n')
        with self.assertRaises(ScnetConfigError):
            ScnetConfig.load(path, env=self.env, use_environment=False)

        nested = self.write_user_config('timeouts:\n  unknown: 1\n', name='nested.yaml')
        with self.assertRaises(ScnetConfigError):
            ScnetConfig.load(nested, env=self.env, use_environment=False)

    def test_invalid_values_raise(self):
        bad_timeout = self.write_user_config('timeouts:\n  request: -1\n', name='t.yaml')
        with self.assertRaises(ScnetConfigError):
            ScnetConfig.load(bad_timeout, env=self.env, use_environment=False)

        bad_path = self.write_user_config('paths:\n  detail: /no/placeholder\n', name='p.yaml')
        with self.assertRaises(ScnetConfigError):
            ScnetConfig.load(bad_path, env=self.env, use_environment=False)

        bad_status = self.write_user_config('statuses:\n  running: []\n', name='s.yaml')
        with self.assertRaises(ScnetConfigError):
            ScnetConfig.load(bad_status, env=self.env, use_environment=False)

    def test_yaml_top_level_must_be_mapping(self):
        path = self.write_user_config('- a\n- b\n')
        with self.assertRaises(ScnetConfigError):
            load_yaml(path)

    def test_describe_masks_secrets(self):
        path = self.write_user_config(USER_YAML)
        text = ScnetConfig.load(path, env=self.env, use_environment=False).describe()
        self.assertNotIn('SK-TEST', text)
        self.assertNotIn('AK-TEST', text)
        self.assertIn('**', text)


class EnvironmentLayerTests(TemporaryConfigMixin):
    def test_env_overrides_user_config(self):
        path = self.write_user_config(USER_YAML)
        env = dict(self.env)
        env.update({
            'SCNET_USER': 'bob',
            'SCNET_CLUSTER_ID': '22222',
            'SCNET_POLL_INTERVAL': '1.5',
            'SCNET_CENTER_URL': 'https://custom.example.com/ac/openapi/v2/center',
            'SCNET_RUNNING_STATUSES': 'running,starting',
        })
        config = ScnetConfig.load(path, env=env, use_environment=True)
        self.assertEqual(config.user, 'bob')
        self.assertEqual(config.cluster_id, '22222')
        self.assertEqual(config.timeouts.poll_interval, 1.5)
        self.assertEqual(config.endpoints.center_url, 'https://custom.example.com/ac/openapi/v2/center')
        self.assertEqual(config.statuses.running, ('running', 'starting'))
        # 未覆盖的项仍来自用户态
        self.assertEqual(config.access_key, 'AK-TEST')

    def test_use_environment_false_ignores_env(self):
        env = {'HOME': str(self.home), 'SCNET_USER': 'bob'}
        config = ScnetConfig.load(env=env, cwd=str(self.work), use_environment=False)
        self.assertIsNone(config.user)

    def test_call_kwargs_win_over_environment(self):
        env = {'HOME': str(self.home), 'SCNET_CLUSTER_ID': '11111'}
        config = ScnetConfig.load(env=env, cwd=str(self.work), cluster_id='33333')
        self.assertEqual(config.cluster_id, '33333')

    def test_resolve_config_path_priority(self):
        explicit = self.write_user_config(USER_YAML, name='explicit.yaml')
        env_file = self.write_user_config(USER_YAML, name='from_env.yaml')
        # 显式 > 环境变量 > 搜索
        resolved = resolve_config_path(
            explicit, env={'SCNET_CONFIG': str(env_file)}, cwd=str(self.work)
        )
        self.assertEqual(resolved, explicit)
        resolved = resolve_config_path(
            None, env={'SCNET_CONFIG': str(env_file)}, cwd=str(self.work)
        )
        self.assertEqual(resolved, env_file)
        self.assertIsNone(resolve_config_path(None, env=self.env, cwd=str(self.work)))

    def test_deep_merge_replaces_lists(self):
        merged = deep_merge(
            {'statuses': {'running': ['a', 'b'], 'terminal': ['x']}},
            {'statuses': {'running': ['c']}},
        )
        self.assertEqual(merged['statuses']['running'], ['c'])
        self.assertEqual(merged['statuses']['terminal'], ['x'])


class ClientConfigTests(TemporaryConfigMixin):
    def test_client_uses_paths_and_timeouts_from_config(self):
        path = self.write_user_config(
            'paths:\n'
            '  task: /custom/task\n'
            '  detail: /custom/{container_id}/detail\n'
            'timeouts:\n'
            '  wait: 0.05\n'
            '  poll_interval: 0.01\n'
        )
        seen = []

        def handler(request):
            seen.append(request.url.path)
            if request.method == 'POST':
                return httpx.Response(200, json={'code': '0', 'msg': 'ok', 'data': 'cid-1'})
            return httpx.Response(
                200, json={'code': '0', 'msg': 'ok', 'data': {'id': 'cid-1', 'status': 'Waiting'}}
            )

        http = httpx.Client(transport=httpx.MockTransport(handler))
        client = ScnetClient.from_config(
            path,
            http_client=http,
            token='tk',
            ai_url='https://host/ai',
            env=self.env,
            use_environment=False,
        )
        self.assertEqual(client.create_container(_minimal_spec()), 'cid-1')
        with self.assertRaises(ScnetTimeoutError):
            client.wait_for_container('cid-1')
        client.close()

        self.assertIn('/ai/custom/task', seen)
        self.assertIn('/ai/custom/cid-1/detail', seen)

    def test_client_kwargs_override_config(self):
        path = self.write_user_config('timeouts:\n  poll_interval: 9\n')
        config = ScnetConfig.load(path, env=self.env, use_environment=False)
        client = ScnetClient(
            config,
            poll_interval=1.5,
            running_statuses=('ready',),
            http_client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
        )
        self.assertEqual(client.config.timeouts.poll_interval, 1.5)
        self.assertEqual(client.config.statuses.running, ('ready',))
        client.close()

    def test_from_config_authenticates_with_aksk(self):
        path = self.write_user_config(USER_YAML)
        calls = []

        def handler(request):
            calls.append((request.url.host, request.url.path))
            if request.url.host == 'api.scnet.cn':
                return httpx.Response(200, json={
                    'code': '0', 'msg': 'success',
                    'data': [{'clusterId': '11112', 'clusterName': 'OpenAPI计算中心', 'token': 'tk-1'}],
                })
            return httpx.Response(200, json={
                'code': '0', 'msg': 'success',
                'data': {'id': 11112, 'aiUrls': [{'enable': 'true', 'url': 'https://hpc.example.com/ai'}]},
            })

        http = httpx.Client(transport=httpx.MockTransport(handler))
        client = ScnetClient.from_config(
            path, http_client=http, env=self.env, use_environment=False
        )
        self.assertEqual(client.token, 'tk-1')
        self.assertEqual(client.ai_url, 'https://hpc.example.com/ai')
        self.assertEqual(client.config.cluster_id, '11112')
        self.assertEqual(calls[0][0], 'api.scnet.cn')
        self.assertEqual(calls[1][0], 'www.scnet.cn')
        client.close()

    def test_from_config_requires_credentials(self):
        config = ScnetConfig.load(env=self.env, search_user_config=False, use_environment=False)
        with self.assertRaises(ScnetConfigError):
            ScnetClient.from_config(config=config)

    def test_from_environment_token_only(self):
        client = ScnetClient.from_environment(
            env={'SCNET_TOKEN': 'tk', 'SCNET_AI_URL': 'https://host/ai'}
        )
        self.assertEqual(client.token, 'tk')
        self.assertEqual(client.ai_url, 'https://host/ai')
        client.close()

    def test_from_environment_requires_something(self):
        with self.assertRaises(ScnetConfigError):
            ScnetClient.from_environment(env={})

    def test_describe_config_is_masked(self):
        path = self.write_user_config(USER_YAML)
        client = ScnetClient.from_config(
            path,
            require_credentials=False,
            http_client=_offline_client(),
            env=self.env,
            use_environment=False,
        )
        text = client.describe_config()
        self.assertNotIn('SK-TEST', text)
        self.assertIn('SCNet SDK 配置', text)
        client.close()

    def test_require_credentials_false_skips_authentication(self):
        path = self.write_user_config(USER_YAML)
        client = ScnetClient.from_config(
            path,
            require_credentials=False,
            http_client=_offline_client(),
            env=self.env,
            use_environment=False,
        )
        # 配置里有 AK/SK，但未要求凭证时不应主动发起认证请求
        self.assertIsNone(client.token)
        self.assertEqual(client.config.user, 'alice')
        client.close()


def _offline_client() -> httpx.Client:
    """禁止真实网络的 httpx.Client：任何请求都会让用例失败。"""

    def handler(request):
        raise AssertionError(f'测试不应发起真实请求: {request.url}')

    return httpx.Client(transport=httpx.MockTransport(handler))


def _minimal_spec():
    from scnet_sdk import ContainerSpec

    return ContainerSpec(
        instance_service_name='Instances_cfg',
        image_path='10.0.35.26:5000/gpu/admin/base/jupyter:4.4-py3.7-cpu',
        version='jupyter:4.4-py3.7-cpu',
        resource_group='TeslaM40',
    )


if __name__ == '__main__':
    unittest.main()
