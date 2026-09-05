### Test Case [case_14]: Bottle Response Cookie Setting
**Description**: Response.set_cookie correctly sets the 'Set-Cookie' header on response.
**Test Steps**:
1. res = Response()
2. res.set_cookie('session', 'xyz123')
3. Assert 'Set-Cookie' in res.headers
4. Assert 'session=xyz123' in res.headers['Set-Cookie']
**Expected Result**: Set-Cookie header is properly formatted.
