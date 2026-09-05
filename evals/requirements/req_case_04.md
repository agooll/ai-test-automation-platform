### Test Case [case_04]: LRUCache Single Item Boundary Eviction
**Description**: An LRUCache with maxsize=1 must evict the first item when a second distinct item is inserted.
**Test Steps**:
1. Initialize cache = LRUCache(maxsize=1)
2. Insert cache['first'] = 10
3. Insert cache['second'] = 20
4. Assert 'first' not in cache
5. Assert cache['second'] == 20
**Expected Result**: Only the newest item remains; previous item is evicted.
