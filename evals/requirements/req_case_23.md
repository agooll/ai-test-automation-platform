### Test Case [case_23]: Directory Traversal Path Injection Prevention
**Description**: static_file rejects paths containing '..' escaping root directory with 403 Forbidden.
**Test Steps**:
1. Call static_file('../passwd', root='/tmp')
2. Catch HTTPError or check response status
3. Assert err.status_code == 403
**Expected Result**: Path traversal is blocked with 403 HTTPError.
