### Test Case [case_03]: Zero Maxsize Cache Invariant
**Description**: When Cache is initialized with maxsize=0, it cannot retain any items.
**Test Steps**:
1. Initialize cache = Cache(maxsize=0)
2. Set cache['a'] = 1
3. Assert 'a' not in cache
4. Assert cache.currsize == 0
**Expected Result**: Cache with maxsize=0 immediately evicts or does not retain items.
