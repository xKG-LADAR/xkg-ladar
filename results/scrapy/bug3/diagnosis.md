

I need to understand the failing test. The test `test_redirect_302_relative` expects that when a redirect location is `///i8n.example2.com/302`, the resulting URL should be `http://i8n.example2.com/302`. But instead, the actual result is `http://www.example.com/i8n.example2.com/302`.

Let me trace through the code:

1. `location = safe_url_string(response.headers['location'])` - converts `///i8n.example2.com/302`
2. Looking at the KG, `safe_url_string` produces `location = '/i8n.example2.com/302'` (the `///` scheme-relative URL gets its netloc stripped because `parts` shows `SplitResult(scheme='', netloc='', path='/i8n.example2.com/302', ...)` - the `safe_url_string` function from w3lib normalizes `///path` to `/path`)
3. `redirected_url = urljoin('http://www.example.com/302', '/i8n.example2.com/302')` → `http://www.example.com/i8n.example2.com/302`

The issue is that `safe_url_string` strips the extra slashes from `///i8n.example2.com/302`, converting what should be a protocol-relative URL (`//i8n.example2.com/302`) into a path (`/i8n.example2.com/302`). 

The fix should handle the `Location` header URL before passing it to `safe_url_string`, or use `urljoin` directly on the raw location. The `urljoin` function correctly handles `///i8n.example2.com/302` by treating `//i8n.example2.com` as a netloc (authority). So the fix is to do `urljoin` first, then apply `safe_url_string` on the result.

### Root Cause
The `safe_url_string` function normalizes `///i8n.example2.com/302` to `/i8n.example2.com/302` (stripping the scheme-relative `//` prefix), which causes `urljoin` to treat it as a relative path instead of an authority-relative URL. The `location` variable ends up as `/i8n.example2.com/302` instead of preserving the `//` prefix that indicates a netloc.

### Location
`scrapy/downloadermiddlewares/redirect.py`, lines 76-78 (in `RedirectMiddleware.process_response`)

### Fix
```diff
--- a/scrapy/downloadermiddlewares/redirect.py
+++ b/scrapy/downloadermiddlewares/redirect.py
@@ -73,9 +73,9 @@ class RedirectMiddleware(BaseRedirectMiddleware):
         if 'Location' not in response.headers or response.status not in allowed_status:
             return response
 
-        location = safe_url_string(response.headers['location'])
+        location = response.headers['location']
 
-        redirected_url = urljoin(request.url, location)
+        redirected_url = safe_url_string(urljoin(request.url, location))
 
         if response.status in (301, 307, 308) or request.method == 'HEAD':
             redirected = request.replace(url=redirected_url)
```

### Explanation
The original code first called `safe_url_string` on the raw `Location` header value, which normalized `///i8n.example2.com/302` to `/i8n.example2.com/302` by collapsing the slashes. When this was then passed to `urljoin`, it was treated as a path relative to the original URL's authority, producing `http://www.example.com/i8n.example2.com/302` instead of the expected `http://i8n.example2.com/302`. 

The fix applies `urljoin` first on the raw location (where `///i8n.example2.com/302` is correctly interpreted as having netloc `i8n.example2.com`), and then applies `safe_url_string` to sanitize the fully resolved URL. This matches the KG error path where `redirected_url` was `http://www.example.com/i8n.example2.com/302` instead of `http://i8n.example2.com/302`.