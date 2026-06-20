### Root Cause
In `_get_proxy` (httpproxy.py:30), `base64.b64encode()` is called with `user_pass` which is a `str` (built via `'%s:%s' % (...)`), but `base64.b64encode()` requires a `bytes`-like object. This causes the `TypeError: a bytes-like object is required, not 'str'`.

### Location
`scrapy/downloadermiddlewares/httpproxy.py`, line 30

### Fix
```diff
--- a/scrapy/downloadermiddlewares/httpproxy.py
+++ b/scrapy/downloadermiddlewares/httpproxy.py
@@ -27,7 +27,7 @@ class HttpProxyMiddleware(object):
 
         if user:
             user_pass = '%s:%s' % (unquote(user), unquote(password))
-            creds = base64.b64encode(user_pass).strip()
+            creds = base64.b64encode(user_pass.encode('utf-8')).strip()
         else:
             creds = None
 
```

### Explanation
The KG shows `user_pass` is the string `'user:pass'` and the `TypeError` ("a bytes-like object is required, not 'str'") is raised in `_get_proxy`. `base64.b64encode()` in Python 3 requires bytes input, so encoding `user_pass` to bytes with `.encode('utf-8')` before passing it to `b64encode` fixes the issue.