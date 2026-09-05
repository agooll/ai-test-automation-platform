### Test Case [case_15]: Integer Route Filter Validation
**Description**: Route filter `<id:int>` matches digits but rejects non-integer strings with 404.
**Test Steps**:
1. app = Bottle()
2. @app.route('/item/<id:int>') def item(id): return str(id * 2)
3. Request '/item/42' succeeds with '84'
4. Request '/item/abc' returns 404 HTTPError
**Expected Result**: Integer filter strictly rejects non-digit input.
