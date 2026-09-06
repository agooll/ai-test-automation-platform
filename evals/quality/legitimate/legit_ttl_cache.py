import pytest
from cachetools import TTLCache

def test_ttl_cache_operations():
    cache = TTLCache(maxsize=3, ttl=60)
    cache['x'] = 100
    cache['y'] = 200
    assert cache['x'] == 100
    assert cache['y'] == 200
    assert len(cache) == 2
    assert cache.maxsize == 3
    assert cache.ttl == 60
