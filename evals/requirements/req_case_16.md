### Test Case [case_16]: Empty Query Parameter Parsing
**Description**: Parsing query strings with empty values returns empty string rather than None or error.
**Test Steps**:
1. req = Request({'QUERY_STRING': 'flag=&key=val'})
2. Assert req.query.get('flag') == ''
3. Assert req.query.get('key') == 'val'
**Expected Result**: Empty parameter value is empty string.
