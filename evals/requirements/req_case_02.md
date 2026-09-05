### Test Case [case_02]: TTLCache Storage and Non-Expired Retrieval
**Description**: Verify that cachetools.TTLCache stores values and allows immediate retrieval before expiration.
**Test Steps**:
1. Initialize cache = TTLCache(maxsize=5, ttl=100)
2. Insert cache['key'] = 'val'
3. Assert cache['key'] == 'val'
4. Assert len(cache) == 1
**Expected Result**: Item is accessible immediately after insertion before ttl expires.
