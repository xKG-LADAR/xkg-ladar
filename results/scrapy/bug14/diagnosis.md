### Root Cause
The `is_gzipped` function in `scrapy/utils/gz.py` performs an exact byte-string comparison (`ctype in (b'application/x-gzip', b'application/gzip')`), but the `Content-Type` header value can have different casing (e.g., `b'Application/X-Gzip'`) or include parameters like `; charset=utf-8`. The function doesn't normalize the case or strip extra parameters before comparison, so it returns `False` when the header has non-lowercase casing or additional parameters.

### Location
`scrapy/utils/gz.py`, line 54-56

### Fix
```diff
--- a/scrapy/utils/gz.py
+++ b/scrapy/utils/gz.py
@@ -53,4 +53,5 @@
 def is_gzipped(response):
     """Return True if the response is gzipped, or False otherwise"""
     ctype = response.headers.get('Content-Type', b'')
-    return ctype in (b'application/x-gzip', b'application/gzip')
+    ctype = ctype.split(b';')[0].strip().lower()
+    return ctype in (b'application/x-gzip', b'application/gzip')
```

### Explanation
The KG shows that `ctype` is `b'Application/X-Gzip'` (mixed case), which fails the exact comparison against lowercase `b'application/x-gzip'`. Additionally, the second test case includes `; charset=utf-8` in the Content-Type value. The fix lowercases the content type and strips any parameters (everything after `;`) before comparison, making the check case-insensitive and parameter-tolerant.