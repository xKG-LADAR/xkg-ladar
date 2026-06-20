### Root Cause
`http.RESPONSES.get(int(status))` returns `None` when the status code (e.g., 573) is not found in the dictionary. This `None` is then passed to `to_native_str`, which calls `to_unicode`, and `to_unicode` raises a `TypeError` because it received `NoneType` instead of bytes, str, or unicode.

### Location
File: `scrapy/utils/response.py`, line 58

### Fix
```diff
--- a/scrapy/utils/response.py
+++ b/scrapy/utils/response.py
@@ -55,4 +55,4 @@
     >>> response_status_message(404)
     '404 Not Found'
     """
-    return '%s %s' % (status, to_native_str(http.RESPONSES.get(int(status))))
+    return '%s %s' % (status, to_native_str(http.RESPONSES.get(int(status), b'Unknown Status')))
```

### Explanation
When a status code like 573 is not present in `http.RESPONSES`, `dict.get()` returns `None` by default. Passing `None` to `to_native_str` → `to_unicode` causes the `TypeError` seen in the KG. The fix provides a default value of `b'Unknown Status'` to `dict.get()`, so that unrecognized status codes produce a meaningful message like `"573 Unknown Status"`, matching the test expectation.