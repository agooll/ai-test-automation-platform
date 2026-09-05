### Test Case [case_09]: @cached Decorator Function Memoization
**Description**: The @cached decorator must cache the return value and prevent redundant function calls.
**Test Steps**:
1. Define a counter and function @cached(cache={}) def compute(x): counter[0] += 1; return x * 2
2. Call compute(5) twice
3. Assert compute returns 10 both times
4. Assert counter[0] == 1 (called only once)
**Expected Result**: Function executes once; second call is served from cache.
