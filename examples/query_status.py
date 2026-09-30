"""仅查询容器执行状态。

用法：
    python examples/query_status.py <容器实例ID> [...]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scnet_sdk import ScnetClient


def describe_status(info) -> str:
    flags = []
    if info.is_running:
        flags.append('运行中')
    if info.is_terminal:
        flags.append('终态')
    return ' / '.join(flags) or '进行中'


def resolve_config_path():
    candidate = os.environ.get('SCNET_CONFIG') or str(Path(__file__).with_name('scnet.yaml'))
    return candidate if Path(candidate).is_file() else None


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    with ScnetClient.from_config(resolve_config_path()) as client:
        for container_id in argv[1:]:
            info = client.get_container_status(container_id)
            print(f'容器 {info.id}')
            print(f'  状态      : {info.status} ({describe_status(info)})')
            print(f'  名称      : {info.instance_service_name}')
            print(f'  资源配置  : {info.resource_spec}')
            print(f'  创建/开始 : {info.create_time} / {info.start_time}')
            print(f'  已运行    : {info.duration} (剩余 {info.remaining_time})')
            for url in info.access_urls:
                print(f'  访问入口  : {url}')
            for source, target in info.mounted_paths:
                print(f'  挂载      : {source} -> {target}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
