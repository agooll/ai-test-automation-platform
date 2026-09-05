### Test Case [case_12]: Empty Cache popitem Safety
**Description**: Calling popitem() on an empty Cache must raise KeyError safely without crashing or returning None.
**Test Steps**:
1. Initialize cache = LRUCache(maxsize=5)
2. Call cache.popitem()
**Expected Result**: KeyError is raised indicating cache is empty.
