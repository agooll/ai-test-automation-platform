### Test Case [case_21]: WSGI Callable Protocol Contract
**Description**: Bottle instance called with (environ, start_response) implements standard WSGI interface.
**Test Steps**:
1. app = Bottle()
2. @app.route('/test') def h(): return 'ok'
3. env = {'PATH_INFO': '/test', 'REQUEST_METHOD': 'GET', 'wsgi.input': None}
4. recorded = {} def start_response(status, headers): recorded['status'] = status
5. body = b''.join(app(env, start_response))
6. Assert recorded['status'] == '200 OK'
7. Assert body == b'ok'
**Expected Result**: Standard WSGI response is returned.
