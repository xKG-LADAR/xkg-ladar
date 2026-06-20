### Root Cause

In `_build_format_filter`, when a negation operator is found (e.g., `!=`, `!^=`, `!$=`, `!*=`), the lambda for `op` is defined as `lambda attr, value: not str_op` instead of `lambda attr, value: not str_op(attr, value)`. This means `op` always returns `False` (since `not str_op` evaluates `str_op` as a truthy function object, yielding `False`) instead of actually negating the result of calling the string operator.

### Location

File: `youtube_dl/YoutubeDL.py`, line within `_build_format_filter` method (the negation lambda).

### Fix

```diff
--- a/youtube_dl/YoutubeDL.py
+++ b/youtube_dl/YoutubeDL.py
@@ -1075,7 +1075,7 @@ class YoutubeDL(object):
                 comparison_value = m.group('value')
                 str_op = STR_OPERATORS[m.group('op')]
                 if m.group('negation'):
-                    op = lambda attr, value: not str_op
+                    op = lambda attr, value: not str_op(attr, value)
                 else:
                     op = str_op
 
```

### Explanation

The KG shows that for the format selector `[format_id!=abc-cba]`, the `str_op` is set to `operator.eq` and `op` is set to a lambda. The test expects that `[format_id!=abc-cba]` should filter out `abc-cba` and return `zxc-cxz`. However, the buggy lambda `lambda attr, value: not str_op` evaluates `not <function>` which is always `False` (a function object is truthy), so every format gets filtered out, leading to `formats_to_download` being empty and raising `ExtractorError('requested format not available')`. The fix calls `str_op(attr, value)` so the negation actually applies to the comparison result.