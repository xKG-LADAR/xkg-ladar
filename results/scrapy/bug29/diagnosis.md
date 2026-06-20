### Root Cause
When `request_httprepr` is called with a non-HTTP request (e.g., `file:///tmp/foo.txt`), `parsed.hostname` is `None` (as shown in the KG where `hostname` is `None`). The function passes `None` to `to_bytes()`, which raises a `TypeError` because `to_bytes` only accepts unicode, str, or bytes objects, not `NoneType`.

### Location
File: `scrapy/utils/request.py`, line 83

### Fix
```diff
--- a/scrapy/utils/request.py
+++ b/scrapy/utils/request.py
@@ -80,7 +80,7 @@
     parsed = urlparse_cached(request)
     path = urlunparse(('', '', parsed.path or '/', parsed.params, parsed.query, ''))
     s = to_bytes(request.method) + b" " + to_bytes(path) + b" HTTP/1.1\r\n"
-    s += b"Host: " + to_bytes(parsed.hostname) + b"\r\n"
+    s += b"Host: " + to_bytes(parsed.hostname or '') + b"\r\n"
     if request.headers:
         s += request.headers.to_string() + b"\r\n"
     s += b"\r\n"
```

### Explanation
The KG shows that for a `file:///tmp/foo.txt` URL, `parsed.hostname` is `None`. When `to_bytes(None)` is called, it raises `TypeError` because `None` is not a `unicode`, `str`, or `bytes` object. The fix replaces `None` with an empty string `''` using `or ''`, which `to_bytes` can handle correctly. This allows `request_httprepr` to work for non-HTTP requests like `file://` and `ftp://` URLs where hostname may be absent.