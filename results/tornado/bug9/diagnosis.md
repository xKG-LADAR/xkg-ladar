### Root Cause
The `url_concat` function does not handle `None` as the `args` parameter. When `args` is `None`, it falls through to the `else` branch and raises a `TypeError` with message "'args' parameter should be dict, list or tuple. Not <class 'NoneType'>". The test `test_url_concat_none_params` expects that passing `None` should return the original URL unchanged.

### Location
`tornado/httputil.py`, lines 608-613 (the `if/elif/else` chain)

### Fix
```diff
--- a/tornado/httputil.py
+++ b/tornado/httputil.py
@@ -605,7 +605,9 @@ def url_concat(url, args):
     'http://example.com/foo?a=b&c=d&c=d2'
     """
     parsed_url = urlparse(url)
-    if isinstance(args, dict):
+    if args is None:
+        return url
+    elif isinstance(args, dict):
         parsed_query = parse_qsl(parsed_url.query, keep_blank_values=True)
         parsed_query.extend(args.items())
     elif isinstance(args, list) or isinstance(args, tuple):
```

### Explanation
The fix adds a check for `None` at the beginning of the `if/elif/else` chain in `url_concat`. When `args is None`, the function simply returns the original URL unchanged, which matches the expected behavior in `test_url_concat_none_params`. This prevents `None` from falling through to the `else` branch that raises a `TypeError`.