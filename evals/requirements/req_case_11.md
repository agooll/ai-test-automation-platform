### Test Case [case_11]: typedkey Type Differentiation
**Description**: cachetools.keys.typedkey must distinguish between integer and float values (e.g. 3 vs 3.0).
**Test Steps**:
1. k_int = typedkey(3)
2. k_float = typedkey(3.0)
3. Assert k_int != k_float
**Expected Result**: Different types produce distinct cache keys preventing type collision.
