"""Generate the 24 Real OSS Benchmark Cases (cachetools & bottle)."""

from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = ROOT / "evals"

REQ_DIR = EVALS_DIR / "requirements"
MUT_DIR = EVALS_DIR / "mutants"
CASE_DIR = EVALS_DIR / "cases"
SUITE_DIR = EVALS_DIR / "suites"

for d in [REQ_DIR, MUT_DIR, CASE_DIR, SUITE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 24 Real OSS Cases: 12 on cachetools (oss_project_1), 12 on bottle (oss_project_2)
CASES = [
    # -------------------------------------------------------------
    # oss_project_1: cachetools (Cases 01 - 12)
    # -------------------------------------------------------------
    # 1. happy_path
    {
        "id": "case_01",
        "project": "oss_project_1",
        "category": "happy_path",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "cachetools.LRUCache",
        "req_text": """### Test Case [case_01]: LRUCache Basic Storage and Retrieval
**Description**: Verify that cachetools.LRUCache correctly stores key-value pairs, retrieves them, and updates currsize.
**Test Steps**:
1. Initialize cache = LRUCache(maxsize=2)
2. Insert cache['a'] = 1 and cache['b'] = 2
3. Assert cache['a'] == 1 and cache['b'] == 2
4. Assert cache.currsize == 2
**Expected Result**: Values are preserved and currsize equals 2.
""",
        "mutant_desc": "LRUCache.__setitem__ always stores None instead of value",
        "mutant_patch": """--- a/src/cachetools/__init__.py
+++ b/src/cachetools/__init__.py
@@ -301,3 +301,3 @@
-        cache_setitem(self, key, value)
+        cache_setitem(self, key, None)
""",
    },
    {
        "id": "case_02",
        "project": "oss_project_1",
        "category": "happy_path",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "cachetools.TTLCache",
        "req_text": """### Test Case [case_02]: TTLCache Storage and Non-Expired Retrieval
**Description**: Verify that cachetools.TTLCache stores values and allows immediate retrieval before expiration.
**Test Steps**:
1. Initialize cache = TTLCache(maxsize=5, ttl=100)
2. Insert cache['key'] = 'val'
3. Assert cache['key'] == 'val'
4. Assert len(cache) == 1
**Expected Result**: Item is accessible immediately after insertion before ttl expires.
""",
        "mutant_desc": "TTLCache forces ttl to 0 on init causing immediate expiration",
        "mutant_patch": """--- a/src/cachetools/__init__.py
+++ b/src/cachetools/__init__.py
@@ -487,3 +487,3 @@
-        self.__ttl = ttl
+        self.__ttl = 0
""",
    },

    # 2. boundary_value
    {
        "id": "case_03",
        "project": "oss_project_1",
        "category": "boundary_value",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "cachetools.Cache",
        "req_text": """### Test Case [case_03]: Zero Maxsize Cache Invariant
**Description**: When Cache is initialized with maxsize=0, it cannot retain any items.
**Test Steps**:
1. Initialize cache = Cache(maxsize=0)
2. Set cache['a'] = 1
3. Assert 'a' not in cache
4. Assert cache.currsize == 0
**Expected Result**: Cache with maxsize=0 immediately evicts or does not retain items.
""",
        "mutant_desc": "Bypasses size eviction check allowing maxsize=0 to retain items",
        "mutant_patch": """--- a/src/cachetools/__init__.py
+++ b/src/cachetools/__init__.py
@@ -86,3 +86,3 @@
-            while self.__currsize + diffsize > maxsize:
+            while self.__currsize + diffsize > maxsize and maxsize > 0:
""",
    },
    {
        "id": "case_04",
        "project": "oss_project_1",
        "category": "boundary_value",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "cachetools.LRUCache",
        "req_text": """### Test Case [case_04]: LRUCache Single Item Boundary Eviction
**Description**: An LRUCache with maxsize=1 must evict the first item when a second distinct item is inserted.
**Test Steps**:
1. Initialize cache = LRUCache(maxsize=1)
2. Insert cache['first'] = 10
3. Insert cache['second'] = 20
4. Assert 'first' not in cache
5. Assert cache['second'] == 20
**Expected Result**: Only the newest item remains; previous item is evicted.
""",
        "mutant_desc": "Disables popitem eviction in __setitem__ allowing size to exceed maxsize",
        "mutant_patch": """--- a/src/cachetools/__init__.py
+++ b/src/cachetools/__init__.py
@@ -86,3 +86,3 @@
-            while self.__currsize + diffsize > maxsize:
-                self.popitem()
+            pass
""",
    },

    # 3. error_handling
    {
        "id": "case_05",
        "project": "oss_project_1",
        "category": "error_handling",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "cachetools.Cache",
        "req_text": """### Test Case [case_05]: Negative Maxsize Rejection
**Description**: Initializing Cache with negative maxsize must raise ValueError.
**Test Steps**:
1. Attempt to initialize Cache(maxsize=-1)
2. Catch ValueError
**Expected Result**: ValueError is raised with 'maxsize must be non-negative'.
""",
        "mutant_desc": "Removes negative maxsize validation check",
        "mutant_patch": """--- a/src/cachetools/__init__.py
+++ b/src/cachetools/__init__.py
@@ -53,3 +53,2 @@
-        if maxsize < 0:
-            raise ValueError("maxsize must be non-negative")
""",
    },
    {
        "id": "case_06",
        "project": "oss_project_1",
        "category": "error_handling",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "cachetools.Cache.__getitem__",
        "req_text": """### Test Case [case_06]: Missing Key KeyError Raising
**Description**: Accessing a non-existent key in Cache must raise KeyError.
**Test Steps**:
1. Initialize cache = Cache(maxsize=10)
2. Access cache['missing_key']
**Expected Result**: KeyError is raised.
""",
        "mutant_desc": "Cache.__getitem__ returns None on KeyError instead of propagating",
        "mutant_patch": """--- a/src/cachetools/__init__.py
+++ b/src/cachetools/__init__.py
@@ -74,3 +74,3 @@
-        except KeyError:
-            return self.__missing__(key)
+        except KeyError:
+            return None
""",
    },

    # 4. concurrency_state
    {
        "id": "case_07",
        "project": "oss_project_1",
        "category": "concurrency_state",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "cachetools.LFUCache",
        "req_text": """### Test Case [case_07]: LFUCache Frequency-Based Eviction
**Description**: LFUCache must evict the least frequently accessed item when capacity is exceeded.
**Test Steps**:
1. Initialize cache = LFUCache(maxsize=2)
2. Insert cache['a'] = 1 and cache['b'] = 2
3. Access cache['a'] 3 times
4. Insert cache['c'] = 3
5. Assert 'b' was evicted and 'a' remains in cache
**Expected Result**: Item 'b' (frequency 1) is evicted; item 'a' (frequency 4) remains.
""",
        "mutant_desc": "LFUCache fails to increment hit count on getitem",
        "mutant_patch": """--- a/src/cachetools/__init__.py
+++ b/src/cachetools/__init__.py
@@ -236,3 +236,2 @@
-        if key in self:  # __missing__ may not store item
-            self.__touch(key)
""",
    },
    {
        "id": "case_08",
        "project": "oss_project_1",
        "category": "concurrency_state",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "cachetools.RRCache",
        "req_text": """### Test Case [case_08]: RRCache Capacity Constraint Invariant
**Description**: RRCache (Random Replacement) must strictly respect maxsize regardless of insertion order.
**Test Steps**:
1. Initialize cache = RRCache(maxsize=3)
2. Insert 10 items into cache
3. Assert len(cache) == 3
4. Assert cache.currsize == 3
**Expected Result**: Size never exceeds maxsize=3.
""",
        "mutant_desc": "RRCache popitem removes nothing",
        "mutant_patch": """--- a/src/cachetools/__init__.py
+++ b/src/cachetools/__init__.py
@@ -341,3 +341,3 @@
-            return (key, self.pop(key))
+            return (key, None)
""",
    },

    # 5. mock_contract
    {
        "id": "case_09",
        "project": "oss_project_1",
        "category": "mock_contract",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "cachetools.cached",
        "req_text": """### Test Case [case_09]: @cached Decorator Function Memoization
**Description**: The @cached decorator must cache the return value and prevent redundant function calls.
**Test Steps**:
1. Define a counter and function @cached(cache={}) def compute(x): counter[0] += 1; return x * 2
2. Call compute(5) twice
3. Assert compute returns 10 both times
4. Assert counter[0] == 1 (called only once)
**Expected Result**: Function executes once; second call is served from cache.
""",
        "mutant_desc": "@cached always calls underlying wrapper bypassing cache lookup",
        "mutant_patch": """--- a/src/cachetools/_cached.py
+++ b/src/cachetools/_cached.py
@@ -48,3 +48,3 @@
-            try:
-                return cache[k]
+            if False:
+                pass
""",
    },
    {
        "id": "case_10",
        "project": "oss_project_1",
        "category": "mock_contract",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "cachetools.keys.hashkey",
        "req_text": """### Test Case [case_10]: hashkey Deterministic Key Construction
**Description**: cachetools.keys.hashkey must return equal keys for identical positional and keyword arguments.
**Test Steps**:
1. k1 = hashkey(1, 'a', x=True)
2. k2 = hashkey(1, 'a', x=True)
3. Assert k1 == k2
4. Assert hash(k1) == hash(k2)
**Expected Result**: Generated keys and hashes are equal.
""",
        "mutant_desc": "hashkey appends random id making identical arguments produce distinct keys",
        "mutant_patch": """--- a/src/cachetools/keys.py
+++ b/src/cachetools/keys.py
@@ -32,3 +32,3 @@
-        return _HashedTuple(key)
+        return _HashedTuple(key + (object(),))
""",
    },

    # 6. security_injection
    {
        "id": "case_11",
        "project": "oss_project_1",
        "category": "security_injection",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "cachetools.keys.typedkey",
        "req_text": """### Test Case [case_11]: typedkey Type Differentiation
**Description**: cachetools.keys.typedkey must distinguish between integer and float values (e.g. 3 vs 3.0).
**Test Steps**:
1. k_int = typedkey(3)
2. k_float = typedkey(3.0)
3. Assert k_int != k_float
**Expected Result**: Different types produce distinct cache keys preventing type collision.
""",
        "mutant_desc": "typedkey fails to include type in tuple matching hashkey behavior",
        "mutant_patch": """--- a/src/cachetools/keys.py
+++ b/src/cachetools/keys.py
@@ -52,3 +52,3 @@
-            key += (type(v), v)
+            key += (v,)
""",
    },
    {
        "id": "case_12",
        "project": "oss_project_1",
        "category": "security_injection",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "cachetools.Cache.popitem",
        "req_text": """### Test Case [case_12]: Empty Cache popitem Safety
**Description**: Calling popitem() on an empty Cache must raise KeyError safely without crashing or returning None.
**Test Steps**:
1. Initialize cache = LRUCache(maxsize=5)
2. Call cache.popitem()
**Expected Result**: KeyError is raised indicating cache is empty.
""",
        "mutant_desc": "LRUCache.popitem returns None instead of raising KeyError when empty",
        "mutant_patch": """--- a/src/cachetools/__init__.py
+++ b/src/cachetools/__init__.py
@@ -312,3 +312,3 @@
-        except StopIteration:
-            raise KeyError("%s is empty" % type(self).__name__) from None
+        except StopIteration:
+            return None
""",
    },

    # -------------------------------------------------------------
    # oss_project_2: bottle (Cases 13 - 24)
    # -------------------------------------------------------------
    # 1. happy_path
    {
        "id": "case_13",
        "project": "oss_project_2",
        "category": "happy_path",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "bottle.Bottle.route",
        "req_text": """### Test Case [case_13]: Bottle Dynamic Route Matching
**Description**: Bottle route matching with wildcard `<name>` passes extracted parameter to handler.
**Test Steps**:
1. app = Bottle()
2. @app.route('/hello/<name>') def greet(name): return f"Hello {name}!"
3. Response for GET '/hello/Alice' via app._handle({'PATH_INFO': '/hello/Alice', 'REQUEST_METHOD': 'GET'})
4. Assert response body contains 'Hello Alice!'
**Expected Result**: Dynamic parameter is correctly captured and returned.
""",
        "mutant_desc": "Bottle._handle ignores handler return value and returns empty body",
        "mutant_patch": """--- a/bottle.py
+++ b/bottle.py
@@ -980,3 +980,3 @@
-                return out
+                return ""
""",
    },
    {
        "id": "case_14",
        "project": "oss_project_2",
        "category": "happy_path",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "bottle.Response.set_cookie",
        "req_text": """### Test Case [case_14]: Bottle Response Cookie Setting
**Description**: Response.set_cookie correctly sets the 'Set-Cookie' header on response.
**Test Steps**:
1. res = Response()
2. res.set_cookie('session', 'xyz123')
3. Assert 'Set-Cookie' in res.headers
4. Assert 'session=xyz123' in res.headers['Set-Cookie']
**Expected Result**: Set-Cookie header is properly formatted.
""",
        "mutant_desc": "Response.set_cookie does not append Set-Cookie header",
        "mutant_patch": """--- a/bottle.py
+++ b/bottle.py
@@ -1674,3 +1674,3 @@
-        self.headers.append('Set-Cookie', ...
+        pass
""",
    },

    # 2. boundary_value
    {
        "id": "case_15",
        "project": "oss_project_2",
        "category": "boundary_value",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "bottle.Router",
        "req_text": """### Test Case [case_15]: Integer Route Filter Validation
**Description**: Route filter `<id:int>` matches digits but rejects non-integer strings with 404.
**Test Steps**:
1. app = Bottle()
2. @app.route('/item/<id:int>') def item(id): return str(id * 2)
3. Request '/item/42' succeeds with '84'
4. Request '/item/abc' returns 404 HTTPError
**Expected Result**: Integer filter strictly rejects non-digit input.
""",
        "mutant_desc": "int route filter regex matches all characters instead of digits",
        "mutant_patch": """--- a/bottle.py
+++ b/bottle.py
@@ -428,3 +428,3 @@
-        'int': r'-?\d+',
+        'int': r'.+',
""",
    },
    {
        "id": "case_16",
        "project": "oss_project_2",
        "category": "boundary_value",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "bottle.Request.query",
        "req_text": """### Test Case [case_16]: Empty Query Parameter Parsing
**Description**: Parsing query strings with empty values returns empty string rather than None or error.
**Test Steps**:
1. req = Request({'QUERY_STRING': 'flag=&key=val'})
2. Assert req.query.get('flag') == ''
3. Assert req.query.get('key') == 'val'
**Expected Result**: Empty parameter value is empty string.
""",
        "mutant_desc": "Query parsing drops parameters with empty values",
        "mutant_patch": """--- a/bottle.py
+++ b/bottle.py
@@ -1420,3 +1420,3 @@
-                pairs.append((k, v))
+                if v: pairs.append((k, v))
""",
    },

    # 3. error_handling
    {
        "id": "case_17",
        "project": "oss_project_2",
        "category": "error_handling",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "bottle.abort",
        "req_text": """### Test Case [case_17]: abort HTTPError Raising
**Description**: bottle.abort(401, 'Unauthorized') raises HTTPError with status_code=401.
**Test Steps**:
1. Call abort(401, 'Unauthorized')
2. Catch HTTPError
3. Assert err.status_code == 401
**Expected Result**: HTTPError(401) is raised.
""",
        "mutant_desc": "abort forces status code 500 regardless of argument",
        "mutant_patch": """--- a/bottle.py
+++ b/bottle.py
@@ -2714,3 +2714,3 @@
-def abort(code=500, text='Unknown Error.'):
-    raise HTTPError(code, text)
+def abort(code=500, text='Unknown Error.'):
+    raise HTTPError(500, text)
""",
    },
    {
        "id": "case_18",
        "project": "oss_project_2",
        "category": "error_handling",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "bottle.redirect",
        "req_text": """### Test Case [case_18]: redirect HTTPResponse Redirection
**Description**: bottle.redirect('/target', code=302) raises HTTPResponse with status 302 and Location header.
**Test Steps**:
1. Call redirect('/target', 302)
2. Catch HTTPResponse
3. Assert res.status_code == 302
4. Assert res.headers['Location'].endswith('/target')
**Expected Result**: HTTPResponse redirect is raised with 302 and Location header.
""",
        "mutant_desc": "redirect forces status 200 instead of 302",
        "mutant_patch": """--- a/bottle.py
+++ b/bottle.py
@@ -2724,3 +2724,3 @@
-    raise HTTPResponse("", status=code, headers=headers)
+    raise HTTPResponse("", status=200, headers=headers)
""",
    },

    # 4. concurrency_state
    {
        "id": "case_19",
        "project": "oss_project_2",
        "category": "concurrency_state",
        "difficulty": "medium",
        "split": "dev",
        "entrypoint": "bottle.Bottle.route",
        "req_text": """### Test Case [case_19]: Distinct Handlers for HTTP Methods on Same Path
**Description**: Same path registered with GET and POST delegates to appropriate method handler.
**Test Steps**:
1. app = Bottle()
2. @app.get('/res') def get_handler(): return 'got'
3. @app.post('/res') def post_handler(): return 'posted'
4. Assert GET request returns 'got'
5. Assert POST request returns 'posted'
**Expected Result**: Method routing accurately separates GET and POST on same URL.
""",
        "mutant_desc": "Route lookup ignores request method and always matches first route",
        "mutant_patch": """--- a/bottle.py
+++ b/bottle.py
@@ -480,3 +480,3 @@
-        methods = self.methods.get(method) or self.methods.get('*')
+        methods = next(iter(self.methods.values()))
""",
    },
    {
        "id": "case_20",
        "project": "oss_project_2",
        "category": "concurrency_state",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "bottle.HeaderDict",
        "req_text": """### Test Case [case_20]: HeaderDict Case-Insensitive Header Lookup
**Description**: HeaderDict must match keys irrespective of casing (e.g. Content-Type vs content-type).
**Test Steps**:
1. hd = HeaderDict()
2. hd['Content-Type'] = 'text/plain'
3. Assert hd['content-type'] == 'text/plain'
4. Assert hd['CONTENT-TYPE'] == 'text/plain'
**Expected Result**: Headers are accessible with any casing.
""",
        "mutant_desc": "HeaderDict converts keys to raw without title/case normalization",
        "mutant_patch": """--- a/bottle.py
+++ b/bottle.py
@@ -1763,3 +1763,3 @@
-        return key.title()
+        return key
""",
    },

    # 5. mock_contract
    {
        "id": "case_21",
        "project": "oss_project_2",
        "category": "mock_contract",
        "difficulty": "easy",
        "split": "dev",
        "entrypoint": "bottle.Bottle.wsgi",
        "req_text": """### Test Case [case_21]: WSGI Callable Protocol Contract
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
""",
        "mutant_desc": "Bottle WSGI start_response called with 500 status",
        "mutant_patch": """--- a/bottle.py
+++ b/bottle.py
@@ -990,3 +990,3 @@
-        start_response(response.status, response.headerlist)
+        start_response("500 Internal Error", response.headerlist)
""",
    },
    {
        "id": "case_22",
        "project": "oss_project_2",
        "category": "mock_contract",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "bottle.FormsDict.decode",
        "req_text": """### Test Case [case_22]: FormsDict Unicode Decoding Contract
**Description**: FormsDict decoded access returns decoded unicode values.
**Test Steps**:
1. fd = FormsDict()
2. fd['text'] = 'hello'.encode('utf-8')
3. Assert fd.decode()['text'] == 'hello'
**Expected Result**: Byte strings are decoded into unicode.
""",
        "mutant_desc": "FormsDict.decode returns raw bytes without decoding",
        "mutant_patch": """--- a/bottle.py
+++ b/bottle.py
@@ -1838,3 +1838,3 @@
-        return copy
+        return self
""",
    },

    # 6. security_injection
    {
        "id": "case_23",
        "project": "oss_project_2",
        "category": "security_injection",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "bottle.static_file",
        "req_text": """### Test Case [case_23]: Directory Traversal Path Injection Prevention
**Description**: static_file rejects paths containing '..' escaping root directory with 403 Forbidden.
**Test Steps**:
1. Call static_file('../passwd', root='/tmp')
2. Catch HTTPError or check response status
3. Assert err.status_code == 403
**Expected Result**: Path traversal is blocked with 403 HTTPError.
""",
        "mutant_desc": "static_file removes path traversal check allowing parent directory access",
        "mutant_patch": """--- a/bottle.py
+++ b/bottle.py
@@ -2500,3 +2500,2 @@
-    if '..' in filename:
-        return HTTPError(403, "Access denied.")
""",
    },
    {
        "id": "case_24",
        "project": "oss_project_2",
        "category": "security_injection",
        "difficulty": "hard",
        "split": "holdout",
        "entrypoint": "bottle.Request.get_cookie",
        "req_text": """### Test Case [case_24]: Signed Cookie Tampering Rejection
**Description**: Request.get_cookie with secret returns None if cookie payload signature was tampered with.
**Test Steps**:
1. req = Request({'HTTP_COOKIE': 'user="tampered_payload_without_valid_sig"'})
2. res = req.get_cookie('user', secret='topsecret')
3. Assert res is None
**Expected Result**: Tampered signed cookie is rejected and returns None.
""",
        "mutant_desc": "get_cookie ignores signature verification and returns raw tampered cookie",
        "mutant_patch": """--- a/bottle.py
+++ b/bottle.py
@@ -1550,3 +1550,3 @@
-        return cookie_decode(value, secret)
+        return value
""",
    },
]

def main():
    case_ids = []
    smoke_case_ids = ["case_01", "case_13"]

    for item in CASES:
        cid = item["id"]
        case_ids.append(cid)

        # 1. Write requirement
        req_rel = f"evals/requirements/req_{cid}.md"
        req_file = ROOT / req_rel
        req_file.write_text(item["req_text"].strip() + "\n", encoding="utf-8")

        # 2. Write mutant patch
        mut_rel = f"evals/mutants/mut_{cid}.patch"
        mut_file = ROOT / mut_rel
        mut_file.write_text(item["mutant_patch"].lstrip(), encoding="utf-8")

        # 3. Write case yaml
        case_yaml_data = {
            "case_id": cid,
            "project_name": item["project"],
            "category": item["category"],
            "difficulty": item["difficulty"],
            "split": item["split"],
            "requirement_path": req_rel,
            "target_entrypoint": item["entrypoint"],
            "timeout_sec": 60,
            "mutants": [
                {
                    "mutant_id": f"mut_{cid}",
                    "description": item["mutant_desc"],
                    "patch_path": mut_rel,
                }
            ],
            "tags": [item["category"], item["difficulty"], item["split"]],
        }

        case_file = CASE_DIR / f"{cid}.yaml"
        case_file.write_text(yaml.dump(case_yaml_data, sort_keys=False), encoding="utf-8")

    # 4. Write smoke suite (1 cachetools, 1 bottle)
    smoke_data = {
        "suite_id": "smoke_v1",
        "description": "Real OSS Smoke Suite (2 cases: 1 cachetools, 1 bottle)",
        "cases": smoke_case_ids,
        "default_repeats": 1,
        "default_timeout_sec": 60,
    }
    (SUITE_DIR / "smoke_v1.yaml").write_text(yaml.dump(smoke_data, sort_keys=False), encoding="utf-8")

    # 5. Write full benchmark suite (24 real OSS cases)
    bench_data = {
        "suite_id": "benchmark_v1",
        "description": "Comprehensive TestTeller Benchmark v1 (24 Real OSS Cases on cachetools & bottle)",
        "cases": case_ids,
        "default_repeats": 3,
        "default_timeout_sec": 60,
    }
    (SUITE_DIR / "benchmark_v1.yaml").write_text(yaml.dump(bench_data, sort_keys=False), encoding="utf-8")

    print(f"Successfully generated {len(case_ids)} Real OSS benchmark cases, requirements, mutants, and suites.")

if __name__ == "__main__":
    main()
