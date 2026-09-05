### Test Case [case_20]: HeaderDict Case-Insensitive Header Lookup
**Description**: HeaderDict must match keys irrespective of casing (e.g. Content-Type vs content-type).
**Test Steps**:
1. hd = HeaderDict()
2. hd['Content-Type'] = 'text/plain'
3. Assert hd['content-type'] == 'text/plain'
4. Assert hd['CONTENT-TYPE'] == 'text/plain'
**Expected Result**: Headers are accessible with any casing.
