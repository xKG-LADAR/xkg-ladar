### Root Cause
The `urljoin` function checks if `base` is a `compat_str` instance, but when `base` is `b'http://foo.de/'` (bytes), it fails the `isinstance(base, compat_str)` check and returns `None` instead of converting the bytes to a string and performing the join. The error message `None != 'http://foo.de/a/b/c.txt'` confirms this — the second test case passes `b'http://foo.de/'` as base and `/a/b/c.txt` as path, but gets `None` back.

### Location
`youtube_dl/utils.py`, line 1750-1757 (the `urljoin` function)

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1748,10 +1748,14 @@ def urljoin(base, path):
 
 
 def urljoin(base, path):
-    if not isinstance(path, compat_str) or not path:
+    if isinstance(path, bytes):
+        path = path.decode('utf-8')
+    if isinstance(base, bytes):
+        base = base.decode('utf-8')
+    if not isinstance(path, compat_str) or not path:
         return None
     if re.match(r'^(?:https?:)?//', path):
         return path
-    if not isinstance(base, compat_str) or not re.match(r'^(?:https?:)?//', base):
+    if not isinstance(base, compat_str) or not re.match(r'^(?:https?:)?//', base):
         return None
     return compat_urlparse.urljoin(base, path)
```

### Explanation
The test passes byte strings (`b'http://foo.de/'` and `b'/a/b/c.txt'`) to `urljoin`, but the function only accepts `compat_str` (which is `str` in Python 3). When bytes are passed, the `isinstance` checks fail and the function returns `None`. The fix converts bytes arguments to strings (UTF-8) before the type checks, allowing the function to handle both `str` and `bytes` inputs correctly. This addresses all four combinations tested: `(str, str)`, `(bytes, str)`, `(str, bytes)`, and `(bytes, bytes)`.