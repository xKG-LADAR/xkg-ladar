### Root Cause
The test expects `parse_dfxp_time_expr('00:00:01:100')` to return `1.1`, but the regex pattern `r'^(\d+):(\d\d):(\d\d(?:\.\d+)?)$'` only matches time expressions with dots (e.g., `00:00:01.100`), not colons as the frame separator (e.g., `00:00:01:100`). The `mobj` is `None` for this input, so the function returns `None` instead of `1.1`.

### Location
`youtube_dl/utils.py`, lines 1986-1988

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1985,6 +1985,10 @@ def parse_dfxp_time_expr(time_expr):
     if mobj:
         return float(mobj.group('time_offset'))
 
-    mobj = re.match(r'^(\d+):(\d\d):(\d\d(?:\.\d+)?)$', time_expr)
+    mobj = re.match(r'^(\d+):(\d\d):(\d\d(?:(?:\.|:)(\d+))?)$', time_expr)
     if mobj:
-        return 3600 * int(mobj.group(1)) + 60 * int(mobj.group(2)) + float(mobj.group(3))
+        result = 3600 * int(mobj.group(1)) + 60 * int(mobj.group(2)) + int(mobj.group(3)[:2])
+        if mobj.group(4):
+            frac = mobj.group(4)
+            result += int(frac) / (10 ** len(frac))
+        return result
```

### Explanation
The original regex only handled the `HH:MM:SS.mmm` format but not the `HH:MM:SS:mmm` format (where milliseconds are separated by a colon instead of a dot). The fix updates the regex to accept either `:` or `.` as the separator before the fractional part, and then computes the fractional seconds correctly from the captured millisecond digits. For `00:00:01:100`, it now correctly returns `1.0 + 100/1000 = 1.1`.