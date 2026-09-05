### Test Case [case_05]: Negative Maxsize Rejection
**Description**: Initializing Cache with negative maxsize must raise ValueError.
**Test Steps**:
1. Attempt to initialize Cache(maxsize=-1)
2. Catch ValueError
**Expected Result**: ValueError is raised with 'maxsize must be non-negative'.
