### Test Case [case_07]: LFUCache Frequency-Based Eviction
**Description**: LFUCache must evict the least frequently accessed item when capacity is exceeded.
**Test Steps**:
1. Initialize cache = LFUCache(maxsize=2)
2. Insert cache['a'] = 1 and cache['b'] = 2
3. Access cache['a'] 3 times
4. Insert cache['c'] = 3
5. Assert 'b' was evicted and 'a' remains in cache
**Expected Result**: Item 'b' (frequency 1) is evicted; item 'a' (frequency 4) remains.
