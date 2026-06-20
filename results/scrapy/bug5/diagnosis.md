### Root Cause
The `follow` method in `scrapy/http/response/__init__.py` does not validate that `url` is not `None` before passing it to `self.urljoin(url)`. When `None` is passed, `urljoin` from the standard library happily accepts `None` and returns the base URL, so no error is raised. The test `test_follow_None_url` expects a `ValueError` to be raised when `url=None` is passed to `follow`.

### Location
File: `scrapy/http/response/__init__.py`, line 124 (within the `follow` method, before `self.urljoin(url)`)

### Fix
```diff
--- a/scrapy/http/response/__init__.py
+++ b/scrapy/http/response/__init__.py
@@ -121,6 +121,8 @@
         """
         if isinstance(url, Link):
             url = url.url
+        elif url is None:
+            raise ValueError("url can't be None")
         url = self.urljoin(url)
         return Request(url, callback,
                        method=method,
```

### Explanation
The KG shows that when `follow` is called with `None`, the execution proceeds through `urljoin` → `_get_url` → `safe_url_string` → `escape_ajax` without raising any error, ultimately resulting in the base URL `'http://example.com'` being used. The test expects a `ValueError` but gets none (the `AssertionError: ValueError not raised by follow`). Adding an explicit check for `None` before `urljoin` ensures the expected `ValueError` is raised.