### Root Cause
The regex pattern in `js_to_json` has `[0-9]+(?=\s*:)` which only matches integers followed by a colon (as object keys). However, plain integer values like `101` in `{"foo":101}` are not matched by any pattern in the regex, so they pass through unmatched. But looking more carefully, the issue is that `101` starts with `1`, which matches `[a-zA-Z_][.a-zA-Z_0-9]*` — no, `1` is not in `[a-zA-Z_]`. Let me re-examine: the regex doesn't have a pattern to match plain decimal integers that are NOT followed by `:`. So `101` is not captured by the regex at all and should pass through unchanged. But the error says `'{"foo":11}'` instead of `'{"foo":101}'`.

The problem is that `101` is being partially matched. The pattern `(?:0[xX][0-9a-fA-F]+|0+[0-7]+)(?:\s*:)?` can match the `01` part of `101` — no, it requires starting with `0`. Looking again at the actual regex: `0+[0-7]+` could match `10` — no, it needs to start with `0`. The real issue: within the string `101`, the character `0` at position 1 triggers `0+[0-7]+` to match `01` (the `0` followed by `1`). This matches `01` as an octal number (value 1), replacing `01` in `101` with `1`, yielding `11`.

The regex needs to ensure these octal/hex patterns only match at word boundaries, not in the middle of a number. Adding `\b` before the pattern (or equivalently, ensuring it doesn't match digits preceded by other digits) fixes this. The fix is to add a negative lookbehind `(?<![0-9])` to the octal/hex integer pattern.

### Location
`youtube_dl/utils.py`, line 1974 (the regex pattern in `re.sub`)

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1970,7 +1970,7 @@ def js_to_json(code):
         "(?:[^"\\]*(?:\\\\|\\['"nurtbfx/\n]))*[^"\\]*"|
         '(?:[^'\\]*(?:\\\\|\\['"nurtbfx/\n]))*[^'\\]*'|
         /\*.*?\*/|,(?=\s*[\]}])|
         [a-zA-Z_][.a-zA-Z_0-9]*|
-        (?:0[xX][0-9a-fA-F]+|0+[0-7]+)(?:\s*:)?|
+        (?<![0-9])(?:0[xX][0-9a-fA-F]+|0+[0-7]+)(?:\s*:)?|
         [0-9]+(?=\s*:)
         ''', fix_kv, code)
```

### Explanation
The input `{"foo":101}` contains `101`. The regex pattern `0+[0-7]+` was matching the substring `01` within `101` (starting at the `0` in the middle of the number). This octal match converted `01` (octal) to `1` (decimal), turning `101` into `11`. Adding `(?<![0-9])` as a negative lookbehind ensures that the octal/hex pattern only matches when not preceded by another digit, preventing partial matches within larger decimal numbers.