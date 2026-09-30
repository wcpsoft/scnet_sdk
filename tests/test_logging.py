"""日志系统测试：分级 logger、handler/formatter、多语言目录、脱敏、上下文。

全部输出写入临时文件，不污染 stderr，也不发起真实网络请求。

运行：
    python -m unittest discover -s tests -t . -v
    python tests/test_logging.py -v
"""
from __future__ import annotations

import asyncio
import json
import logging as pylogging
import logging.config
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
    JsonFormatter,
    LogHandlerConfig,
    LoggingConfig,
    ScnetClient,
    ScnetConfig,
    ScnetConfigError,
    TextFormatter,
    available_languages,
    bind_context,
    clear_context,
    configure_logging,
    current_context,
    current_language,
    get_logger,
    is_configured,
    log_context,
    log_event,
    logging_config_dict,
    mask_fields,
    render_event,
    reset_logging,
    set_language,
)
from scnet_sdk.logging import DEBUG, ERROR, INFO, WARNING  # noqa: E402

AI_URL = 'https://hpc.example.com/ai'
CID = '530491fa7c8e47348f01de73e627a6a7'
JWT = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyIjoiaGFvd2oifQ.mprLWvhNLNK1YuQVLewnJ7AG10K'


def spec():
    return ContainerSpec(
        instance_service_name='Instances_log',
        image_path='10.0.35.26:5000/gpu/admin/base/jupyter:4.4-py3.7-cpu',
        version='jupyter:4.4-py3.7-cpu',
        resource_group='TeslaM40',
    )


class LoggingTestCase(unittest.TestCase):
    """统一把日志写到临时文件，避免 stderr 噪音与测试间串扰。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.log_file = self.dir / 'scnet.log'
        reset_logging()
        self.addCleanup(reset_logging)

    def configure(self, fmt: str = 'text', **overrides) -> LoggingConfig:
        config = LoggingConfig(
            level=overrides.pop('level', 'DEBUG'),
            format=fmt,
            handlers=(LogHandlerConfig(type='file', format=fmt, path=str(self.log_file)),),
            **overrides,
        )
        configure_logging(config, force=True)
        return config

    def lines(self):
        if not self.log_file.is_file():
            return []
        return [line for line in self.log_file.read_text(encoding='utf-8').splitlines() if line]

    def records(self):
        return [json.loads(line) for line in self.lines()]

    def last_line(self) -> str:
        lines = self.lines()
        return lines[-1] if lines else ''


class LanguageTests(LoggingTestCase):
    def test_messages_follow_configured_language(self):
        self.configure(language='zh_CN')
        log_event(get_logger('client'), INFO, 'container.create.ok', container_id=CID)
        self.assertIn('容器实例创建成功', self.last_line())

        self.configure(language='en_US')
        log_event(get_logger('client'), INFO, 'container.create.ok', container_id=CID)
        self.assertIn('container instance created', self.last_line())

    def test_builtin_languages_are_packaged(self):
        languages = available_languages()
        self.assertIn('zh_CN', languages)
        self.assertIn('en_US', languages)

    def test_per_record_language_override(self):
        self.configure(language='zh_CN')
        log_event(
            get_logger('client'),
            INFO,
            'container.create.ok',
            container_id=CID,
            log_language='en_US',
        )
        line = self.last_line()
        self.assertIn('container instance created', line)
        # log_language 是保留字段，只用于选语言，不应作为字段输出
        self.assertNotIn('log_language=', line)

    def test_language_is_a_normal_field(self):
        self.configure(language='en_US')
        log_event(
            get_logger('client'),
            INFO,
            'container.create.ok',
            container_id=CID,
            language='payload-marker',
        )
        # language 未被保留字段占用，可正常作为业务字段输出
        self.assertIn('language=payload-marker', self.last_line())

    def test_unknown_event_falls_back_to_event_name(self):
        self.configure(language='zh_CN')
        log_event(get_logger('client'), INFO, 'custom.unknown.event', foo='bar')
        self.assertIn('custom.unknown.event', self.last_line())

    def test_missing_language_pack_falls_back_and_warns(self):
        self.configure(language='fr_FR')
        warnings_found = [
            line for line in self.lines() if 'fr_FR' in line and 'en_US' in line
        ]
        self.assertTrue(warnings_found, self.lines())
        # 回退后仍按英文目录渲染
        log_event(get_logger('client'), INFO, 'container.create.ok', container_id=CID)
        self.assertIn('container instance created', self.last_line())

    def test_custom_catalog_extends_languages(self):
        catalog_dir = self.dir / 'locales'
        catalog_dir.mkdir()
        (catalog_dir / 'fr_FR.yaml').write_text(
            'language: fr_FR\nevents:\n'
            '  container.create.ok: "conteneur créé id={container_id}"\n',
            encoding='utf-8',
        )
        self.configure(language='fr_FR', catalog=str(catalog_dir))
        log_event(get_logger('client'), INFO, 'container.create.ok', container_id=CID)
        self.assertIn('conteneur créé', self.last_line())
        self.assertIn('fr_FR', available_languages())

    def test_set_language_and_current_language(self):
        self.configure(language='en_US')
        self.assertEqual(current_language(), 'en_US')
        self.assertEqual(set_language('zh_CN'), 'zh_CN')
        self.assertEqual(current_language(), 'zh_CN')
        with self.assertRaises(ScnetConfigError):
            set_language('')

    def test_render_event_appends_fields_when_placeholder_missing(self):
        message = render_event('container.create.ok', {'other': 1}, 'zh_CN')
        self.assertIn('容器实例创建成功', message)
        self.assertIn('other', message)


class FormatTests(LoggingTestCase):
    def test_text_format_has_level_logger_and_fields(self):
        self.configure()
        log_event(get_logger('client'), INFO, 'container.create.ok', container_id=CID)
        line = self.last_line()
        self.assertIn('INFO', line)
        self.assertIn('scnet_sdk.client', line)
        self.assertIn(f'container_id={CID}', line)

    def test_json_format_is_structured_and_language_neutral(self):
        self.configure(fmt='json', language='zh_CN')
        log_event(get_logger('client'), INFO, 'container.create.ok', container_id=CID)
        record = self.records()[-1]
        self.assertEqual(record['event'], 'container.create.ok')
        self.assertEqual(record['level'], 'INFO')
        self.assertEqual(record['logger'], 'scnet_sdk.client')
        self.assertEqual(record['language'], 'zh_CN')
        self.assertEqual(record['fields']['container_id'], CID)
        self.assertIn('容器实例创建成功', record['message'])

    def test_secrets_are_masked(self):
        self.configure(fmt='json')
        log_event(
            get_logger('auth'),
            INFO,
            'auth.token.start',
            user='bob',
            token=JWT,
            access_key='934e4dd887264b63a797ccb27f86048f',
            secret_key='short',
        )
        raw = self.log_file.read_text(encoding='utf-8')
        self.assertNotIn(JWT, raw)
        self.assertNotIn('934e4dd887264b63a797ccb27f86048f', raw)
        self.assertIn('***', raw)

    def test_jwt_inside_url_is_masked(self):
        self.configure()
        log_event(
            get_logger('client'),
            DEBUG,
            'request.start',
            method='GET',
            url=f'{AI_URL}/detail?token={JWT}',
        )
        raw = self.log_file.read_text(encoding='utf-8')
        self.assertNotIn(JWT, raw)
        self.assertIn('***', raw)

    def test_masking_can_be_disabled(self):
        self.configure(mask_secrets=False)
        log_event(get_logger('auth'), INFO, 'auth.token.start', user='bob', token=JWT)
        self.assertIn(JWT, self.log_file.read_text(encoding='utf-8'))

    def test_mask_fields_helper(self):
        masked = mask_fields({'token': JWT, 'user': 'bob', 'nested': {'secret_key': 'abcdefghijkl'}})
        self.assertEqual(masked['token'], '***')
        self.assertEqual(masked['user'], 'bob')
        self.assertEqual(masked['nested']['secret_key'], '***')

    def test_build_formatter_unknown_name(self):
        from scnet_sdk import build_formatter

        with self.assertRaises(ScnetConfigError):
            build_formatter('xml', LoggingConfig())

    def test_formatters_are_importable_for_dictconfig(self):
        self.assertEqual(TextFormatter.__module__, 'scnet_sdk.logging')
        self.assertEqual(JsonFormatter.__module__, 'scnet_sdk.logging')


class ContextTests(LoggingTestCase):
    def test_log_context_injects_fields(self):
        self.configure(fmt='json')
        with log_context(request_id='req-1', tenant='acme'):
            log_event(get_logger('client'), INFO, 'container.create.ok', container_id=CID)
        record = self.records()[-1]
        self.assertEqual(record['context'], {'request_id': 'req-1', 'tenant': 'acme'})
        self.assertEqual(record['fields']['container_id'], CID)

    def test_context_is_cleared_after_exit(self):
        self.configure()
        with log_context(request_id='req-1'):
            pass
        self.assertEqual(current_context(), {})
        log_event(get_logger('client'), INFO, 'container.create.ok', container_id=CID)
        self.assertNotIn('request_id', self.last_line())

    def test_bind_and_clear_context(self):
        self.configure()
        bind_context(request_id='req-2')
        self.assertEqual(current_context()['request_id'], 'req-2')
        log_event(get_logger('client'), INFO, 'container.create.ok', container_id=CID)
        self.assertIn('request_id=req-2', self.last_line())
        clear_context()
        self.assertEqual(current_context(), {})


class HierarchyTests(LoggingTestCase):
    def test_get_logger_builds_package_hierarchy(self):
        self.assertEqual(get_logger().name, 'scnet_sdk')
        self.assertEqual(get_logger('client').name, 'scnet_sdk.client')
        self.assertEqual(get_logger('scnet_sdk.auth').name, 'scnet_sdk.auth')

    def test_per_logger_level_override(self):
        self.configure(level='WARNING', loggers={'client': 'DEBUG'})
        log_event(get_logger('client'), DEBUG, 'container.create.ok', container_id=CID)
        log_event(get_logger(), DEBUG, 'container.create.ok', container_id='root')
        lines = self.lines()
        self.assertEqual(len(lines), 1)
        self.assertIn(CID, lines[0])

    def test_root_level_filters_lower_records(self):
        self.configure(level='ERROR')
        log_event(get_logger('client'), INFO, 'container.create.ok', container_id=CID)
        self.assertEqual(self.lines(), [])
        log_event(get_logger('client'), ERROR, 'container.create.ok', container_id=CID)
        self.assertEqual(len(self.lines()), 1)

    def test_console_and_file_shortcuts(self):
        config = LoggingConfig(level='INFO', console=True, file=str(self.log_file), format='json')
        self.assertEqual([item.type for item in config.resolved_handlers()], ['console', 'file'])
        explicit = LoggingConfig(handlers=(LogHandlerConfig(type='file', path='x.log'),))
        self.assertEqual(len(explicit.resolved_handlers()), 1)

    def test_configure_is_idempotent(self):
        config = self.configure()
        root = pylogging.getLogger('scnet_sdk')
        before = len(root.handlers)
        configure_logging(config)  # 不带 force 的重复调用不应重复挂 handler
        self.assertEqual(len(root.handlers), before)
        self.assertTrue(is_configured())

    def test_force_rebuilds_handlers(self):
        self.configure(level='INFO')
        root = pylogging.getLogger('scnet_sdk')
        configure_logging(
            LoggingConfig(
                level='DEBUG',
                handlers=(LogHandlerConfig(type='file', path=str(self.dir / 'other.log')),),
            ),
            force=True,
        )
        managed = [h for h in root.handlers if getattr(h, '_scnet_managed', False)]
        self.assertEqual(len(managed), 1)
        self.assertEqual(Path(managed[0].baseFilename).name, 'other.log')

    def test_reset_logging_removes_managed_handlers(self):
        self.configure()
        reset_logging()
        self.assertFalse(is_configured())
        root = pylogging.getLogger('scnet_sdk')
        self.assertEqual([h for h in root.handlers if getattr(h, '_scnet_managed', False)], [])

    def test_propagate_flag_is_applied(self):
        self.configure(propagate=False)
        self.assertFalse(pylogging.getLogger('scnet_sdk').propagate)
        configure_logging(LoggingConfig(propagate=True), force=True)
        self.assertTrue(pylogging.getLogger('scnet_sdk').propagate)


class DictConfigTests(LoggingTestCase):
    def test_logging_config_dict_usable_with_dictconfig(self):
        target = self.dir / 'dict.log'
        payload = logging_config_dict(LoggingConfig(
            level='INFO',
            format='json',
            propagate=False,
            handlers=(LogHandlerConfig(type='file', path=str(target), format='json'),),
        ))
        self.assertEqual(payload['version'], 1)
        self.assertFalse(payload['disable_existing_loggers'])
        self.assertEqual(payload['loggers']['scnet_sdk']['level'], 'INFO')
        self.assertEqual(
            payload['handlers']['scnet_file_0']['class'], 'logging.handlers.RotatingFileHandler'
        )
        self.assertEqual(payload['formatters']['scnet_json']['()'], 'scnet_sdk.logging.JsonFormatter')

        root = pylogging.getLogger('scnet_sdk')
        saved = list(root.handlers)
        try:
            logging.config.dictConfig(payload)
            log_event(get_logger('client'), INFO, 'container.create.ok', container_id=CID)
            record = json.loads(target.read_text(encoding='utf-8').strip().splitlines()[-1])
            self.assertEqual(record['event'], 'container.create.ok')
            self.assertEqual(record['fields']['container_id'], CID)
        finally:
            for handler in list(root.handlers):
                root.removeHandler(handler)
                handler.close()
            root.handlers.extend(saved)

    def test_console_handler_uses_ext_stream(self):
        payload = logging_config_dict(LoggingConfig(console=True))
        self.assertEqual(payload['handlers']['scnet_console_0']['stream'], 'ext://sys.stderr')


class ConfigIntegrationTests(LoggingTestCase):
    def test_logging_section_from_env(self):
        config = ScnetConfig.load(
            env={'HOME': '/nonexistent', 'SCNET_LOG_LEVEL': 'DEBUG',
                 'SCNET_LOG_LANGUAGE': 'en_US', 'SCNET_LOG_FORMAT': 'json',
                 'SCNET_LOG_CONSOLE': 'true'},
            cwd='/nonexistent',
            use_environment=True,
        )
        self.assertEqual(config.logging.level, 'DEBUG')
        self.assertEqual(config.logging.language, 'en_US')
        self.assertEqual(config.logging.format, 'json')
        self.assertTrue(config.logging.console)

    def test_logging_section_from_yaml(self):
        path = self.dir / 'scnet.yaml'
        path.write_text(
            'logging:\n'
            '  level: INFO\n'
            '  language: en_US\n'
            '  handlers:\n'
            '    - type: file\n'
            '      path: /tmp/scnet-test.log\n'
            '      format: json\n'
            '  loggers:\n'
            '    client: DEBUG\n',
            encoding='utf-8',
        )
        config = ScnetConfig.load(path, env={'HOME': '/nonexistent'}, use_environment=False)
        self.assertEqual(config.logging.level, 'INFO')
        self.assertEqual(config.logging.language, 'en_US')
        self.assertEqual(len(config.logging.handlers), 1)
        self.assertEqual(config.logging.handlers[0].type, 'file')
        self.assertEqual(config.logging.handlers[0].format, 'json')
        self.assertEqual(config.logging.loggers, {'client': 'DEBUG'})

    def test_invalid_logging_section_raises(self):
        path = self.dir / 'bad.yaml'
        path.write_text('logging:\n  level: LOUD\n', encoding='utf-8')
        with self.assertRaises(ScnetConfigError):
            ScnetConfig.load(path, env={'HOME': '/nonexistent'}, use_environment=False)

        path.write_text('logging:\n  unknown: 1\n', encoding='utf-8')
        with self.assertRaises(ScnetConfigError):
            ScnetConfig.load(path, env={'HOME': '/nonexistent'}, use_environment=False)

        path.write_text('logging:\n  handlers:\n    - type: file\n', encoding='utf-8')
        with self.assertRaises(ScnetConfigError):
            ScnetConfig.load(path, env={'HOME': '/nonexistent'}, use_environment=False)

    def test_configure_from_scnet_config(self):
        config = ScnetConfig.load(
            env={'HOME': '/nonexistent', 'SCNET_LOG_LEVEL': 'INFO'},
            cwd='/nonexistent',
        )
        configured = configure_logging(config, force=True, language='zh_CN')
        self.assertEqual(configured.level, 'INFO')
        self.assertEqual(configured.language, 'zh_CN')

    def test_describe_shows_logging_settings(self):
        text = ScnetConfig.load(env={'HOME': '/nonexistent'}, use_environment=False).describe()
        self.assertIn('日志', text)


class ClientLoggingTests(LoggingTestCase):
    def build_client(self):
        def handler(request):
            if request.method == 'POST':
                return httpx.Response(200, json={'code': '0', 'msg': 'ok', 'data': CID})
            if request.method == 'DELETE':
                return httpx.Response(200, json={'code': '0', 'msg': 'ok', 'data': None})
            return httpx.Response(
                200, json={'code': '0', 'msg': 'ok', 'data': {'id': CID, 'status': 'Running'}}
            )

        return ScnetClient(
            token='token-abc',
            ai_url=AI_URL,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            search_user_config=False,
            use_environment=False,
        )

    def test_client_emits_full_lifecycle_events(self):
        self.configure(fmt='json', language='zh_CN')
        client = self.build_client()
        client.create_container(spec())
        client.get_container(CID)
        client.delete_containers([CID])
        client.close()

        events = {record['event'] for record in self.records() if record.get('event')}
        self.assertLessEqual(
            {
                'container.create.start',
                'container.create.ok',
                'request.start',
                'request.finish',
                'container.detail',
                'container.delete.start',
                'container.delete.ok',
            },
            events,
        )

    def test_client_logs_never_contain_token(self):
        self.configure()
        client = self.build_client()
        client.create_container(spec())
        client.close()
        raw = self.log_file.read_text(encoding='utf-8')
        self.assertNotIn('token-abc', raw)
        self.assertIn('容器实例创建成功', raw)


class AsyncClientLoggingTests(LoggingTestCase):
    def test_async_client_emits_events(self):
        self.configure(fmt='json', language='en_US')
        asyncio.run(self._exercise_async_client())

        events = {record['event'] for record in self.records() if record.get('event')}
        self.assertIn('container.create.ok', events)
        self.assertIn('container.delete.ok', events)
        self.assertIn('container instance created', self.log_file.read_text(encoding='utf-8'))

    async def _exercise_async_client(self):
        async def handler(request):
            if request.method == 'POST':
                return httpx.Response(200, json={'code': '0', 'msg': 'ok', 'data': CID})
            if request.method == 'DELETE':
                return httpx.Response(200, json={'code': '0', 'msg': 'ok', 'data': None})
            return httpx.Response(
                200, json={'code': '0', 'msg': 'ok', 'data': {'id': CID, 'status': 'Waiting'}}
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            client = AsyncScnetClient(
                token='token-abc',
                ai_url=AI_URL,
                http_client=http,
                search_user_config=False,
                use_environment=False,
            )
            await client.create_container(spec())
            await client.get_container(CID)
            await client.delete_containers([CID])
        finally:
            await http.aclose()


if __name__ == '__main__':
    unittest.main()
