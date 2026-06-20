### Root Cause
The regex pattern `([{,]\s*)` requires that a key-value pair be preceded by `{` or `,`. When the value is `{` (an opening brace for a nested object), the regex matches the outer `'clip':{'provider'...` but the inner `'provider':'pseudo'` is not matched because the `{` that precedes it was already consumed as the `value` capture group (group 4) of the previous match. The `{` captured as `value` means the next key-value pair `'provider':'pseudo'` starts after `{`, but the regex needs `{` to be part of group 1 `([{,]\s*)` of the next match, which it can't be since it was already consumed.

### Location
`youtube_dl/utils.py`, line 1601 (the regex pattern in `re.sub`)

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1597,7 +1597,7 @@ def js_to_json(code):
     res = re.sub(r'''(?x)
             ([{,]\s*)
             ("[^"]*"|\'[^\']*\'|[a-z0-9A-Z]+)
             (:\s*)
-            ([0-9.]+|true|false|"[^"]*"|\'[^\']*\'|\[|\{)
+            ([0-9.]+|true|false|"[^"]*"|\'[^\']*\'|\[|\{(?![^\s]))
         ''', fix_kv, code)
     res = re.sub(r',(\s*\])', lambda m: m.group(1), res)
     return res
```

Wait, let me reconsider. The real issue is that when `value` is `{`, it gets consumed by the first match, so the subsequent `'provider':'pseudo'` can't match because the `{` before it is gone. The fix should avoid consuming `{` as part of the match so it remains available for the next match.

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1597,7 +1597,7 @@ def js_to_json(code):
     res = re.sub(r'''(?x)
-            ([{,]\s*)
+            ((?:[{,])\s*)
             ("[^"]*"|\'[^\']*\'|[a-z0-9A-Z]+)
             (:\s*)
-            ([0-9.]+|true|false|"[^"]*"|\'[^\']*\'|\[|\{)
+            ([0-9.]+|true|false|"[^"]*"|\'[^\']*\'|\[)
         ''', fix_kv, code)
     res = re.sub(r',(\s*\])', lambda m: m.group(1), res)
     return res
```

Hmm, but that would break `value` handling for `{`. Let me think more carefully.

The real solution: when the value is `{` or `[`, we shouldn't consume it, so the next match can use it as the start delimiter. We should use a lookahead instead.

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1598,7 +1598,7 @@ def js_to_json(code):
             ([{,]\s*)
             ("[^"]*"|\'[^\']*\'|[a-z0-9A-Z]+)
             (:\s*)
-            ([0-9.]+|true|false|"[^"]*"|\'[^\']*\'|\[|\{)
+            ([0-9.]+|true|false|"[^"]*"|\'[^\']*\'|(?=[\[{]))
         ''', fix_kv, code)
     res = re.sub(r',(\s*\])', lambda m: m.group(1), res)
     return res
```

### Explanation
When the value is `{` or `[` (start of a nested object/array), consuming it prevents the next key-value pair inside that nested structure from being matched (since the regex requires `{` or `,` at the start). By changing `\[|\{` to a lookahead `(?=[\[{])`, we assert the presence of `{` or `[` without consuming it. This way `{` remains in the string and serves as the leading delimiter for the next match. The `value` group will capture an empty string when the value is a nested structure, which is fine since it doesn't need transformation — it's just a structural character.