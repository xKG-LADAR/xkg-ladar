### Root Cause
The regex in `unescapeHTML` uses `r'&([^;]+;)'` which greedily matches from `&` to the last `;` in the string. For input `'&a&quot;'`, the regex matches `&a&quot;` as a single match (entity = `a&quot`), rather than correctly matching only `&quot;`. The regex should match from `&` to the *first* semicolon, not greedily consuming all characters up to the last one.

### Location
File: `youtube_dl/utils.py`, line 599 (the `re.sub` call in `unescapeHTML`)

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -596,4 +596,4 @@ def unescapeHTML(s):
     assert type(s) == compat_str
 
     return re.sub(
-        r'&([^;]+;)', lambda m: _htmlentity_transform(m.group(1)), s)
+        r'&([^&;]+;)', lambda m: _htmlentity_transform(m.group(1)), s)
```

### Explanation
The original regex `[^;]+` matches one or more characters that are not `;`, but it allows `&` characters within the match. For input `&a&quot;`, this causes the regex to match the entire `&a&quot;` as one entity. By changing the character class to `[^&;]+` (excluding both `&` and `;`), the regex correctly fails to match `&a` (since there's no `;` before the next `&`) and instead matches only `&quot;`, producing the expected output `&a"`.