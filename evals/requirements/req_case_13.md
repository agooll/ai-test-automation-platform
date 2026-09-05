### Test Case [case_13]: Bottle Dynamic Route Matching
**Description**: Bottle route matching with wildcard `<name>` passes extracted parameter to handler.
**Test Steps**:
1. app = Bottle()
2. @app.route('/hello/<name>') def greet(name): return f"Hello {name}!"
3. Response for GET '/hello/Alice' via app._handle({'PATH_INFO': '/hello/Alice', 'REQUEST_METHOD': 'GET'})
4. Assert response body contains 'Hello Alice!'
**Expected Result**: Dynamic parameter is correctly captured and returned.
