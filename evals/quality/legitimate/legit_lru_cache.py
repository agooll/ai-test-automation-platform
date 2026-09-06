import pytest
from cachetools import LRUCache

def test_lru_cache_operations():
    cache = LRUCache(maxsize=2)
    cache['a'] = 1
    cache['b'] = 2
    assert cache['a'] == 1
    assert cache['b'] == 2
    assert len(cache) == 2

    # Access 'a' so 'b' becomes least recently used
    _ = cache['a']
    cache['c'] = 3

    assert 'a' in cache
    assert 'c' in cache
    assert 'b' not in cache
    with pytest.raises(KeyError):
        _ = cache['b']
