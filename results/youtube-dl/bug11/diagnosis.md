### Root Cause
The `str_to_int` function calls `re.sub()` on `int_str` without first checking if it's already an `int`. When `test_str_to_int` passes `523` (an integer), `re.sub()` raises a `TypeError` because it expects a string or bytes-like object, not an `int`.

### Location
`youtube_dl/utils.py`, lines 3520-3526

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -3522,5 +3522,7 @@ def str_to_int(int_str):
     """ A more relaxed version of int_or_none """
     if int_str is None:
         return None
+    if isinstance(int_str, compat_str):
+        int_str = re.sub(r'[,\.\+]', '', int_str)
-    int_str = re.sub(r'[,\.\+]', '', int_str)
     return int(int_str)
```

### Explanation
When `int_str` is already an integer (e.g., `523`), the `re.sub()` call fails because it expects a string input. The fix wraps the `re.sub()` call in a type check so that the regex substitution is only applied when `int_str` is a string. If it's already a numeric type, it skips directly to `int()` conversion. The `compat_str` reference is used for Python 2/3 compatibility, which is standard in this codebase. If `compat_str` is not available in scope, `str` can be used instead.