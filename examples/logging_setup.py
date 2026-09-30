"""日志系统示例：多语言、结构化 JSON、脱敏、请求上下文、dictConfig 集成。

不需要任何凭证，直接运行即可看到输出：
    python examples/logging_setup.py
    SCNET_LOG_LANGUAGE=en_US python examples/logging_setup.py
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scnet_sdk  # noqa: E402
from scnet_sdk import ScnetConfig  # noqa: E402

JWT_SAMPLE = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyIjoiYm9iIn0.SflKxwRJSM'


def demo_text(language: str) -> None:
    print(f'=== 1. 文本格式（中文/英文可切换）language={language} ===')
    scnet_sdk.configure_logging(
        level='DEBUG', language=language, console=True, format='text', force=True
    )
    logger = scnet_sdk.get_logger('demo')

    scnet_sdk.log_event(logger, logging.INFO, 'container.create.ok', container_id='c-1234')
    scnet_sdk.log_event(
        logger,
        logging.DEBUG,
        'request.start',
        method='POST',
        url='https://hpc.example.com/ai/openapi/v2/instance-service/task',
    )
    # 敏感字段自动打码
    scnet_sdk.log_event(
        logger,
        logging.INFO,
        'auth.token.start',
        user='bob',
        timestamp='1764597591',
        token=JWT_SAMPLE,
        access_key='934e4dd887264b63a797ccb27f86048f',
    )

    with scnet_sdk.log_context(request_id='req-1', tenant='acme'):
        scnet_sdk.log_event(logger, logging.DEBUG, 'container.wait.poll', attempt=2, status='Waiting')


def demo_json(language: str) -> None:
    print(f'\n=== 2. JSON 结构化输出（event 与语言无关）language={language} ===')
    scnet_sdk.configure_logging(
        level='INFO', language=language, console=True, format='json', force=True
    )
    logger = scnet_sdk.get_logger('client')
    scnet_sdk.log_event(logger, logging.INFO, 'container.create.ok', container_id='c-1234')
    scnet_sdk.log_event(logger, logging.ERROR, 'container.wait.terminal', container_id='c-1234', status='Failed')


def demo_filtering() -> None:
    print('\n=== 3. 分级 logger（log4j 的 logger 层级）===')
    config = scnet_sdk.LoggingConfig(
        level='WARNING',
        language='zh_CN',
        console=True,
        loggers={'client': 'DEBUG'},   # 只有 scnet_sdk.client 输出 DEBUG
    )
    scnet_sdk.configure_logging(config, force=True)

    client_logger = scnet_sdk.get_logger('client')
    other_logger = scnet_sdk.get_logger('demo')
    print('# 下面一行来自 scnet_sdk.client（DEBUG 已放开）：')
    scnet_sdk.log_event(client_logger, logging.DEBUG, 'container.detail', container_id='c-1234', status='Waiting')
    print('# 下面这行 DEBUG 会被 WARNING 级别过滤掉，不会出现：')
    scnet_sdk.log_event(other_logger, logging.DEBUG, 'container.detail', container_id='c-1234', status='Waiting')


def demo_dictconfig() -> None:
    print('\n=== 4. 与宿主框架集成：dictConfig 片段 ===')
    payload = scnet_sdk.logging_config_dict(scnet_sdk.LoggingConfig(
        level='INFO',
        language='en_US',
        format='json',
        propagate=False,
        handlers=(
            scnet_sdk.LogHandlerConfig(type='file', path='logs/scnet-demo.log', format='json'),
        ),
    ))
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main() -> int:
    language = ScnetConfig.load().logging.language
    print(f'配置中的日志语言: {language}')
    print(f'可用语言: {scnet_sdk.available_languages()}\n')

    demo_text(language)
    demo_json(language)
    scnet_sdk.configure_logging(level='WARNING', console=True, force=True)
    demo_filtering()
    demo_dictconfig()

    scnet_sdk.reset_logging()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
