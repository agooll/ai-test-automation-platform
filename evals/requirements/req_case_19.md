### Test Case [case_19]: Distinct Handlers for HTTP Methods on Same Path
**Description**: Same path registered with GET and POST delegates to appropriate method handler.
**Test Steps**:
1. app = Bottle()
2. @app.get('/res') def get_handler(): return 'got'
3. @app.post('/res') def post_handler(): return 'posted'
4. Assert GET request returns 'got'
5. Assert POST request returns 'posted'
**Expected Result**: Method routing accurately separates GET and POST on same URL.
