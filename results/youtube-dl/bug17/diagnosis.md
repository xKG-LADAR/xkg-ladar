### Root Cause
The `cli_bool_option` function always asserts that `param` is a `bool` (`assert isinstance(param, bool)`), but when the parameter key is not present in the `params` dictionary, `params.get(param)` returns `None`. The test expects an empty list `[]` to be returned when the key is missing, but instead the assertion fails because `None` is not a `bool`.

### Location
File: `youtube_dl/utils.py`, lines 2735-2740

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -2734,7 +2734,8 @@ def cli_bool_option(params, command_option, param, true_value='true', false_valu
 def cli_bool_option(params, command_option, param, true_value='true', false_value='false', separator=None):
     param = params.get(param)
-    assert isinstance(param, bool)
+    if param is None:
+        return []
+    assert isinstance(param, bool)
     if separator:
         return [command_option + separator + (true_value if param else false_value)]
     return [command_option, true_value if param else false_value]
```

### Explanation
When the test calls `cli_bool_option({}, '--check-certificate', 'nocheckcertificate', 'false', 'true', '=')`, the key `'nocheckcertificate'` is not in the empty dict `{}`, so `params.get(param)` returns `None`. The existing code then hits `assert isinstance(param, bool)` which fails since `None` is not a `bool`. The fix adds a check for `None` before the assertion, returning an empty list `[]` as the test expects.