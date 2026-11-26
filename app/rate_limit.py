"""进程内滑动窗口限流。

项目按单进程部署设计；如果以后改成多进程，需要换成 Redis 等共享存储。
"""
import time
from collections import defaultdict, deque

_EVENTS = defaultdict(deque)


def _prune(key, window):
    queue = _EVENTS.get(key)
    if not queue:
        return
    cutoff = time.monotonic() - window
    while queue and queue[0] < cutoff:
        queue.popleft()
    if not queue:
        _EVENTS.pop(key, None)


def blocked(key, limit, window):
    _prune(key, window)
    return len(_EVENTS.get(key, ())) >= limit


def fail(key, window):
    _prune(key, window)
    _EVENTS[key].append(time.monotonic())


def reset(key):
    _EVENTS.pop(key, None)


def clear():
    _EVENTS.clear()
