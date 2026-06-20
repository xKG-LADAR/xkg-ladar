### Root Cause
The regex in `url_basename` uses `(?:[^/?#]+/)?` which only matches **one** optional path segment before the final segment. For URLs with multiple path segments like `http://media.w3.org/2010/05/sintel/trailer.mp4` (which has 4 segments: `2010`, `05`, `sintel`, `trailer.mp4`), the regex fails to match, so `m` is `None` and the function returns `''` instead of `'trailer.mp4'`.

### Location
`youtube_dl/utils.py`, line 1090

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1087,7 +1087,7 @@
 
 
 def url_basename(url):
-    m = re.match(r'(?:https?:|)//[^/]+/(?:[^/?#]+/)?([^/?#]+)/?(?:[?#]|$)', url)
+    m = re.match(r'(?:https?:|)//[^/]+/(?:[^/?#]+/)*([^/?#]+)/?(?:[?#]|$)', url)
     if not m:
         return u''
     return m.group(1)
```

### Explanation
Changing `(?:[^/?#]+/)?` (matches zero or one path segments) to `(?:[^/?#]+/)*` (matches zero or more path segments) allows the regex to handle URLs with any number of intermediate path directories. This fixes the case where `http://media.w3.org/2010/05/sintel/trailer.mp4` has multiple path segments before the final filename.