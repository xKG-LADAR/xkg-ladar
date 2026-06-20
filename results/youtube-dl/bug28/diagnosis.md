### Root Cause
When `_htmlentity_transform` encounters a numeric HTML entity with a value outside the valid Unicode range (like `&#2013266066;`), `chr(int(numstr, base))` raises a `ValueError` because `2013266066` exceeds `0x110000`. The function doesn't handle this case and lets the exception propagate, but the test expects the original entity string `'&#2013266066;'` to be returned unchanged.

### Location
`youtube_dl/utils.py`, lines 398-400 (the `return compat_chr(int(numstr, base))` line within `_htmlentity_transform`)

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -395,7 +395,10 @@ def _htmlentity_transform(entity):
             numstr = '0%s' % numstr
         else:
             base = 10
-        return compat_chr(int(numstr, base))
+        # If the number is outside valid Unicode range, return the entity as-is
+        i = int(numstr, base)
+        if 0 <= i <= 0x10ffff:
+            return compat_chr(i)
 
     # Unknown entity in name, return its literal representation
     return ('&%s;' % entity)
```

### Explanation
The numeric entity `&#2013266066;` matches the regex pattern `#[0-9]+`, so `numstr` becomes `'2013266066'` and `base` is `10`. When `int(numstr, base)` produces `2013266066`, calling `compat_chr()` (i.e., `chr()`) raises `ValueError` because the value exceeds the maximum Unicode code point (`0x10FFFF`). The fix checks whether the integer is within the valid Unicode range before calling `compat_chr()`. If it's out of range, execution falls through to the final return statement which returns the literal representation `'&%s;' % entity`, matching the expected test output `'&#2013266066;'`.