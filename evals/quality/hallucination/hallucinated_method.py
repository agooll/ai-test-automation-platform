from cachetools import LRUCache

def test_hallucinated_method():
    c = LRUCache(maxsize=10)
    res = c.nonexistent_super_flush_everything()
    assert res == 1
