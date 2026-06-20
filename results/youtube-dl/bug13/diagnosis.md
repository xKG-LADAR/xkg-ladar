### Root Cause
The `urljoin` function checks if `path` matches `^(?:https?:)?//` to determine if it's an absolute URL that should be returned as-is. However, this regex only matches `http://`, `https://`, or `//` prefixed URLs. When `path` is `'rtmp://foo.de'` (a non-HTTP scheme), it doesn't match this pattern, so the function falls through to check `base`. When `base` is `None` or invalid, the function returns `None` instead of returning the absolute `rtmp://` URL. The fix should recognize any scheme (not just http/https) as an absolute URL in the `path`.

### Location
`youtube_dl/utils.py`, line 1872

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1869,7 +1869,7 @@ def urljoin(base, path):
         path = path.decode('utf-8')
     if not isinstance(path, compat_str) or not path:
         return None
-    if re.match(r'^(?:https?:)?//', path):
+    if re.match(r'^(?:[a-zA-Z][a-zA-Z0-9+\-.]*:)?//', path):
         return path
     if isinstance(base, bytes):
         base = base.decode('utf-8')
```

### Explanation
The original regex `^(?:https?:)?//` only matched paths starting with `http://`, `https://`, or `//`. URLs with other schemes like `rtmp://foo.de` were not recognized as absolute URLs, causing the function to try to join them with a base URL or return `None` if the base was invalid. The fix broadens the regex to match any valid URI scheme (per RFC 3986: a letter followed by letters, digits, `+`, `-`, or `.`) followed by `://`, or just `//`. This correctly identifies `rtmp://foo.de` as an absolute URL and returns it directly.