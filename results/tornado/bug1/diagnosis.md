

### Root Cause

The `get_async_test_timeout` function uses `os.environ.get("ASYNC_TEST_TIMEOUT")` which correctly returns `None` when the key is absent. However, the KG shows a `KeyError` for `b'ASYNC_TEST_TIMEOUT'` (note the bytes prefix `b'`), which indicates that somewhere else in the code, `os.environb` (the bytes-based environment dict) is being accessed with a bytes key, or `os.environ` is being accessed with bracket notation using a bytes key. Looking more carefully at the KG, the error is marked as "raises (caught)", so this isn't the actual test failure.

Let me re-examine the KG. The test `test_nodelay` connects via websocket, reads a message expecting `"hello"`, but the issue is in the `__setitem__` calling `__missing__` - specifically the `__setitem__` node points to `options.py:163`, not `httputil.py`. This means `HTTPHeaders.__setitem__` is being routed to `options.py:163`'s `__setitem__`, which is an `OptionParser.__setitem__`. The `__setitem__` label says `options.py:163`, meaning header setting operations are incorrectly going through the options module instead of httputil's HTTPHeaders.

Looking at the `__missing__` node at `httputil.py:87` and `__setitem__` at `options.py:163` - the `__setitem__` in options.py is likely overriding or interfering with HTTPHeaders. But actually, the `normalized` values show `Sec-Websocket-Key` and `Sec-Websocket-Version` - the hyphen-separated words are being title-cased. The server likely expects `Sec-WebSocket-Key` (with capital S in Socket) but receives `Sec-Websocket-Key`. This is the `_normalize_name` function in `httputil.py` that title-cases each word split by hyphens, turning `Sec-WebSocket-Key` into `Sec-Websocket-Key`.

### Location

`tornado/httputil.py`, around line 87 in the `__missing__` method of `_NormalizedHeaderCache`.

### Fix

```diff
--- a/tornado/httputil.py
+++ b/tornado/httputil.py
@@ -84,7 +84,7 @@ class _NormalizedHeaderCache(dict):
 
     def __missing__(self, key: str) -> str:
         normalized = "-".join([w.capitalize() for w in key.split("-")])
-        self[key] = normalized
+        self[key] = key
         return normalized
```

Wait, that would break normalization entirely. Let me reconsider.

The actual issue is that `Sec-WebSocket-Key` becomes `Sec-Websocket-Key` because `capitalize()` lowercases all characters after the first. The fix should preserve the original casing pattern expected by WebSocket servers.

### Fix

```diff
--- a/tornado/httputil.py
+++ b/tornado/httputil.py
@@ -84,7 +84,7 @@ class _NormalizedHeaderCache(dict):
 
     def __missing__(self, key: str) -> str:
-        normalized = "-".join([w.capitalize() for w in key.split("-")])
+        normalized = "-".join([w[0].upper() + w[1:] if w else w for w in key.split("-")])
         self[key] = normalized
         return normalized
```

### Explanation

The `str.capitalize()` method uppercases the first letter but **lowercases all remaining letters**. So when `Sec-WebSocket-Key` is split by `-` into `['Sec', 'WebSocket', 'Key']`, calling `.capitalize()` on `WebSocket` produces `Websocket` (lowering the `S`). This causes the WebSocket handshake to fail because the header name `Sec-Websocket-Key` doesn't match the expected `Sec-WebSocket-Key`. The fix changes the normalization to only uppercase the first character of each segment while preserving the case of the remaining characters, so `WebSocket` stays as `WebSocket`.