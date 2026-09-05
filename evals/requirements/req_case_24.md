### Test Case [case_24]: Signed Cookie Tampering Rejection
**Description**: Request.get_cookie with secret returns None if cookie payload signature was tampered with.
**Test Steps**:
1. req = Request({'HTTP_COOKIE': 'user="tampered_payload_without_valid_sig"'})
2. res = req.get_cookie('user', secret='topsecret')
3. Assert res is None
**Expected Result**: Tampered signed cookie is rejected and returns None.
