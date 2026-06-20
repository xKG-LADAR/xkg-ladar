

### Root Cause
The regex in `js_to_json` doesn't match plain decimal integers that are NOT followed by a colon (i.e., used as values rather than keys). The pattern `[0-9]+(?={skip}:)` only matches integers followed by `:`, so when `{42:4.2e1}` is processed, `4.2e1` is not matched and not preserved as a number. Additionally, the identifier pattern `[a-zA-Z_][.a-zA-Z_0-9]*` doesn't cover numbers like `4.2e1`. The error `Expecting ',' delimiter: line 1 column 10 (char 9)` indicates the output JSON is malformed because the float value `4.2e1` gets incorrectly quoted/transformed.

Looking more carefully: the regex matches `4` via... no, `[0-9]+(?={skip}:)` requires a colon after. So `4` in `4.2e1` doesn't match any pattern. The `.2e1` part — `.` doesn't match, `2e1` doesn't match `[a-zA-Z_]` pattern. The issue is that decimal/float numbers (like `4.2e1`, `42`, etc.) used as values are not captured by the regex. The pattern needs to also match plain decimal integers and floating point numbers.

### Location
`youtube_dl/utils.py`, lines 2268-2273 (the regex in the `re.sub` call)

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -2265,7 +2265,8 @@ def js_to_json(code):
         "(?:[^"\\]*(?:\\\\|\\['"nurtbfx/\n]))*[^"\\]*"|
         '(?:[^'\\]*(?:\\\\|\\['"nurtbfx/\n]))*[^'\\]*'|
         {comment}|,(?={skip}[\]}}])|
-        [a-zA-Z_][.a-zA-Z_0-9]*|
+        [a-zA-Z_$][.a-zA-Z_$0-9]*|
+        [0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?|
         \b(?:0[xX][0-9a-fA-F]+|0+[0-7]+)(?:{skip}:)?|
         [0-9]+(?={skip}:)
         '''.format(comment=COMMENT_RE, skip=SKIP_RE), fix_kv, code)
```

Wait, the ordering matters. The hex/octal patterns need to come before the general number pattern. Let me reconsider:

```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -2267,7 +2267,8 @@ def js_to_json(code):
         {comment}|,(?={skip}[\]}}])|
         [a-zA-Z_][.a-zA-Z_0-9]*|
         \b(?:0[xX][0-9a-fA-F]+|0+[0-7]+)(?:{skip}:)?|
-        [0-9]+(?={skip}:)
+        [0-9]+(?={skip}:)|
+        [0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?
         '''.format(comment=COMMENT_RE, skip=SKIP_RE), fix_kv, code)
```

### Explanation
The regex in `js_to_json` only matched decimal integers when followed by a colon (`[0-9]+(?={skip}:)`), meaning they were only recognized as object keys. Floating point numbers like `4.2e1` and plain decimal integer values were not matched at all, causing them to pass through unprocessed and potentially break the JSON output. Adding `[0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?` as an additional alternative captures decimal integers and floating-point numbers (including scientific notation) used as values, which then pass through `fix_kv` and get returned as-is (wrapped in quotes via `'"%s"' % v`, but since they don't match the integer table patterns, they need to be kept as literal numbers). 

Wait — `fix_kv` would wrap them in quotes with `'"%s"' % v`, turning `4.2e1` into `"4.2e1"` which is a string, not a number. Let me re-examine.

The `fix_kv` function returns `'"%s"' % v` for unrecognized values. So `4.2e1` would become `"4.2e1"` — a string. We need to handle this in `fix_kv` too.

```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -2257,6 +2257,9 @@ def js_to_json(code):
             if im:
                 i = int(im.group(1), base)
                 return '"%d":' % i if v.endswith(':') else '%d' % i
+        
+        if re.match(r'^[0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?$', v):
+            return v
 
         return '"%s"' % v
 
@@ -2267,7 +2270,8 @@ def js_to_json(code):
         {comment}|,(?={skip}[\]}}])|
         [a-zA-Z_][.a-zA-Z_0-9]*|
         \b(?:0[xX][0-9a-fA-F]+|0+[0-7]+)(?:{skip}:)?|
-        [0-9]+(?={skip}:)
+        [0-9]+(?={skip}:)|
+        [0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?
         '''.format(comment=COMMENT_RE, skip=SKIP_RE), fix_kv, code)
```

### Explanation
Two changes are needed: (1) The regex must capture floating-point and scientific notation numbers (e.g., `4.2e1`) by adding an alternative `[0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?`. (2) The `fix_kv` function must recognize these numeric values and return them as-is (not quoted), so they remain valid JSON numbers. Without both changes, `{42:4.2e1}` fails because `4.2e1` is either unmatched by the regex or incorrectly stringified by `fix_kv`.