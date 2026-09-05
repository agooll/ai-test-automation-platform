### Test Case [case_18]: redirect HTTPResponse Redirection
**Description**: bottle.redirect('/target', code=302) raises HTTPResponse with status 302 and Location header.
**Test Steps**:
1. Call redirect('/target', 302)
2. Catch HTTPResponse
3. Assert res.status_code == 302
4. Assert res.headers['Location'].endswith('/target')
**Expected Result**: HTTPResponse redirect is raised with 302 and Location header.
