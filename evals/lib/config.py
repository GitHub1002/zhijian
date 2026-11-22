"""把评测 JSON 配置覆盖到 app.config，供各评测脚本共用。"""


def apply_config(config, overrides):
    """只覆盖 config 中已存在的属性，返回实际生效的键值。"""
    applied = {}
    for key, value in (overrides or {}).items():
        if not hasattr(config, key):
            continue
        current = getattr(config, key)
        if isinstance(current, bool):
            applied[key] = bool(value)
        elif isinstance(current, int) and not isinstance(current, bool):
            applied[key] = int(value)
        elif isinstance(current, float):
            applied[key] = float(value)
        else:
            applied[key] = value
        setattr(config, key, applied[key])
    return applied
