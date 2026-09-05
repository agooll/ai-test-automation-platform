### Test Case [case_10]: hashkey Deterministic Key Construction
**Description**: cachetools.keys.hashkey must return equal keys for identical positional and keyword arguments.
**Test Steps**:
1. k1 = hashkey(1, 'a', x=True)
2. k2 = hashkey(1, 'a', x=True)
3. Assert k1 == k2
4. Assert hash(k1) == hash(k2)
**Expected Result**: Generated keys and hashes are equal.
