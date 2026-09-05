### Test Case [case_08]: RRCache Capacity Constraint Invariant
**Description**: RRCache (Random Replacement) must strictly respect maxsize regardless of insertion order.
**Test Steps**:
1. Initialize cache = RRCache(maxsize=3)
2. Insert 10 items into cache
3. Assert len(cache) == 3
4. Assert cache.currsize == 3
**Expected Result**: Size never exceeds maxsize=3.
