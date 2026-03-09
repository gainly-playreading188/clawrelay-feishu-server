"""
全局任务注册表

管理 registry_key -> asyncio.Task 映射，支持取消正在运行的任务。
registry_key 格式: "{bot_key}:{session_key}"
"""

import asyncio
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class TaskRegistry:
    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._stream_ids: dict[str, str] = {}
        self._lock = threading.Lock()

    def register(self, key: str, task: asyncio.Task, stream_id: str):
        with self._lock:
            self._tasks[key] = task
            self._stream_ids[key] = stream_id

        def _cleanup(t: asyncio.Task, _key=key):
            with self._lock:
                if self._tasks.get(_key) is t:
                    del self._tasks[_key]
                    self._stream_ids.pop(_key, None)

        task.add_done_callback(_cleanup)

    def cancel(self, key: str) -> tuple[bool, Optional[str]]:
        with self._lock:
            task = self._tasks.get(key)
            stream_id = self._stream_ids.get(key)
            if not task or task.done():
                return False, None
            task.cancel()
            logger.info("[TaskRegistry] 取消任务: key=%s", key)
            return True, stream_id

    def is_running(self, key: str) -> bool:
        with self._lock:
            task = self._tasks.get(key)
            return task is not None and not task.done()


_global_task_registry: Optional[TaskRegistry] = None
_registry_lock = threading.Lock()


def get_task_registry() -> TaskRegistry:
    global _global_task_registry
    if _global_task_registry is None:
        with _registry_lock:
            if _global_task_registry is None:
                _global_task_registry = TaskRegistry()
    return _global_task_registry
