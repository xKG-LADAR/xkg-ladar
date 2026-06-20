

### Root Cause

The `_NormalizedHeaderCache.__missing__` method uses `w.capitalize()` to normalize header name parts, which in Python 3 lowercases all characters after the first. So `"Sec-WebSocket-Version"` is split into `["Sec", "WebSocket", "Version"]`, and `"WebSocket".capitalize()` produces `"Websocket"` (lowercase 's'), resulting in `"Sec-Websocket-Version"` instead of the expected `"Sec-WebSocket-Version"`. This causes the server-side WebSocket handshake code to fail to find the `Sec-WebSocket-Version` header (or `Sec-WebSocket-Key`), because the normalized form doesn't match what the WebSocket code expects.

### Location

`tornado/httputil.py`, line 91 (the `__missing__` method of `_NormalizedHeaderCache`)

### Fix

```diff
--- a/tornado/httputil.py
+++ b/tornado/httputil.py
@@ -88,7 +88,7 @@ class _NormalizedHeaderCache(dict):
         self.queue = collections.deque()
 
     def __missing__(self, key):
-        normalized = "-".join([w.capitalize() for w in key.split("-")])
+        normalized = "-".join([w[0].upper() + w[1:] if w else w for w in key.split("-")])
         self[key] = normalized
         self.queue.append(key)
         if len(self.queue) > self.size:
```

### Explanation

The KG shows that the header `"Sec-WebSocket-Version"` is being normalized to `"Sec-Websocket-Version"` (note the lowercase 's' in 'Websocket'). This happens because Python's `str.capitalize()` uppercases the first character but **lowercases all remaining characters**. So `"WebSocket".capitalize()` → `"Websocket"`. The fix changes the normalization to only uppercase the first character of each dash-separated word while preserving the case of all subsequent characters (`w[0].upper() + w[1:]`). This ensures `"Sec-WebSocket-Version"` stays as `"Sec-WebSocket-Version"`, allowing the WebSocket handshake code to properly detect the missing `Sec-WebSocket-Key` header and return the expected 400 response.