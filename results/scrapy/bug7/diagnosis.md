

I need to understand the flow. The test expects that `<form action=" path\n">` results in URL `http://example.com/path`. The form's `action` attribute is `" path\n"` (with leading space and trailing newline).

Let me trace the flow:
1. `_get_form_url` calls `urljoin(form.base_url, form.action)` 
2. `form.action` returns the raw action attribute value `" path\n"` from lxml
3. `urljoin("http://example.com", " path\n")` would give `"http://example.com/ path\n"` or similar
4. The URL then goes through `safe_url_string` which encodes the space as `%20`

The issue is that the form action attribute `" path\n"` contains leading/trailing whitespace that should be stripped before being used. Looking at `_get_form_url`:

```python
def _get_form_url(form, url):
    if url is None:
        return urljoin(form.base_url, form.action)
    return urljoin(form.base_url, url)
```

The `form.action` value contains spaces and newlines that aren't being stripped. According to HTML spec, attribute values for URLs should have leading/trailing whitespace stripped.

The fix should strip the action value in `_get_form_url`.

### Root Cause
The `_get_form_url` function uses `form.action` directly without stripping leading/trailing whitespace characters. When the HTML contains `action=" path\n"`, `form.action` returns `" path\n"`, and `urljoin` preserves the spaces/newlines, resulting in an incorrect URL like `http://example.com/%20path%0A` instead of `http://example.com/path`.

### Location
`scrapy/http/request/form.py`, line 55 (inside `_get_form_url`)

### Fix
```diff
--- a/scrapy/http/request/form.py
+++ b/scrapy/http/request/form.py
@@ -52,6 +52,6 @@
 
 def _get_form_url(form, url):
     if url is None:
-        return urljoin(form.base_url, form.action)
+        return urljoin(form.base_url, strip_url(form.action))
     return urljoin(form.base_url, url)
```

Wait, I need to check what imports are available. Let me look at the actual stripping needed — the action value is `" path\n"` and the expected result is path `"/path"`. So we just need to `.strip()` the whitespace.

### Fix
```diff
--- a/scrapy/http/request/form.py
+++ b/scrapy/http/request/form.py
@@ -52,5 +52,5 @@
 
 def _get_form_url(form, url):
     if url is None:
-        return urljoin(form.base_url, form.action)
+        return urljoin(form.base_url, form.action.strip())
     return urljoin(form.base_url, url)
```

### Explanation
When lxml parses `<form action=" path\n">`, `form.action` returns the raw attribute value `" path\n"` including leading spaces and trailing newlines. Per the HTML specification, URL attributes should have leading and trailing ASCII whitespace stripped before resolution. By calling `.strip()` on `form.action`, the value becomes `"path"`, which when joined with the base URL `"http://example.com"` via `urljoin` produces the correct `"http://example.com/path"`, matching the test's expected output.