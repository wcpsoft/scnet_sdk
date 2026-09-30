"""异步版：创建容器 -> 等待就绪 -> 执行脚本 -> 查询状态 -> 删除容器。

与同步示例 `create_and_wait.py` 流程一致，区别是全程 await、不阻塞事件循环。

用法：
    # 方式一：使用本目录的示例配置（先填好凭证）
    python examples/create_and_wait_async.py

    # 方式二：用环境变量提供凭证
    export SCNET_USER=... SCNET_ACCESS_KEY=... SCNET_SECRET_KEY=...
    python examples/create_and_wait_async.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scnet_sdk import (
    AsyncScnetClient,
    ContainerSpec,
    MountInfo,
    PortInfo,
    ScnetConfig,
    join_script_lines,
)

# 示例配置里的占位值：避免拿假凭证去请求真实接口
PLACEHOLDER_VALUES = {
    'your-user',
    'your-access-key',
    'your-secret-key',
    'your-ak',
    'your-sk',
}


def resolve_config_path() -> str:
    """优先用 SCNET_CONFIG / 本目录 scnet.yaml，找不到则交给环境变量。"""
    candidate = os.environ.get('SCNET_CONFIG') or str(Path(__file__).with_name('scnet.yaml'))
    return candidate if Path(candidate).is_file() else None


def placeholder_hint(config) -> str:
    """检测示例占位凭证，返回提示文本；无占位则返回空串。"""
    found = PLACEHOLDER_VALUES & {
        value for value in (config.user, config.access_key, config.secret_key) if value
    }
    if not found:
        return ''
    return (
        f'检测到示例配置中的占位凭证 {sorted(found)}。\n'
        '请编辑 examples/scnet.yaml 填入真实凭证，'
        '或用环境变量 SCNET_USER / SCNET_ACCESS_KEY / SCNET_SECRET_KEY 提供。'
    )


async def main() -> int:
    resource_group = os.environ.get('SCNET_RESOURCE_GROUP', 'TeslaM40')
    accelerator_type = os.environ.get('SCNET_ACCELERATOR_TYPE', 'gpu')

    config = ScnetConfig.load(resolve_config_path())
    hint = placeholder_hint(config)
    if hint:
        print(hint)
        return 2

    async with await AsyncScnetClient.from_config(config=config) as client:
        print(client.describe_config())
        print('-' * 60)

        limits = await client.resource_limits(resource_group, accelerator_type)
        print(
            f'节点资源限额: cpu={limits.cpu_number} gpu={limits.gpu_number} '
            f'mem={limits.memory_size}MB maxTime={limits.max_time}'
        )

        spec = ContainerSpec(
            instance_service_name='Instances_demo_async_0001',
            image_path=os.environ.get(
                'SCNET_IMAGE_PATH',
                '10.0.35.26:5000/gpu/admin/base/jupyter:4.4-py3.7-cpu',
            ),
            version=os.environ.get('SCNET_IMAGE_VERSION', 'jupyter:4.4-py3.7-cpu'),
            resource_group=resource_group,
            accelerator_type=accelerator_type,
            task_type='ssh',
            cpu_number=3,
            ram_size=15360,
            gpu_number=1,
            timeout_limit=os.environ.get('SCNET_TIMEOUT_LIMIT', 'unlimited'),
            description='scnet_sdk async demo',
            mounts=[MountInfo('/public1/home/username/test_mount', '/mnt/test_mount', 'data')],
            ports=[PortInfo(18888, 'HTTP')],
        )

        container_id = await client.create_container(spec)
        print(f'创建成功, 容器实例 ID: {container_id}')

        try:
            async def on_poll(attempt: int, current) -> None:
                print(f'  [{attempt}] status={current.status} duration={current.duration}')

            info = await client.wait_for_container(container_id, on_poll=on_poll)
            print(f'容器就绪: status={info.status} spec={info.resource_spec}')
            for url in info.access_urls:
                print(f'  访问入口: {url}')

            await client.execute_script(
                container_id,
                join_script_lines(['echo "hello world"', 'nvidia-smi -L']),
                scope='all',
            )
            print('脚本下发完成')
            print(f'当前状态: {(await client.get_container_status(container_id)).status}')
        finally:
            await client.delete_containers([container_id])
            print(f'已删除容器: {container_id}')

    return 0


async def wait_many(container_ids, **kwargs):
    """并发等待多个容器就绪（异步的典型收益）。"""
    async with await AsyncScnetClient.from_config(resolve_config_path()) as client:
        return await asyncio.gather(
            *(client.wait_for_container(cid, **kwargs) for cid in container_ids)
        )


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
