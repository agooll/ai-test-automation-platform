### Test Case [case_22]: FormsDict Unicode Decoding Contract
**Description**: FormsDict decoded access returns decoded unicode values.
**Test Steps**:
1. fd = FormsDict()
2. fd['text'] = 'hello'.encode('utf-8')
3. Assert fd.decode()['text'] == 'hello'
**Expected Result**: Byte strings are decoded into unicode.
