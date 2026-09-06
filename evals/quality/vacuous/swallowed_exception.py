from cachetools import LRUCache

def test_swallow_error():
    c = LRUCache(maxsize=2)
    try:
        val = c["nonexistent"]
    except Exception:
        pass
