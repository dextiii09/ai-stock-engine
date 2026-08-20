import json
import time

_cache = {}

async def set_cache(key: str, value: dict, expire: int = 3600):
    _cache[key] = {
        "value": value,
        "expires_at": time.time() + expire
    }

async def get_cache(key: str):
    if key in _cache:
        item = _cache[key]
        if time.time() < item["expires_at"]:
            return item["value"]
        else:
            del _cache[key]
    return None

async def delete_cache(key: str):
    if key in _cache:
        del _cache[key]
