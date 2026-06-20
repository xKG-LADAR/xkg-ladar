### Root Cause
The `from_content_disposition` method calls `to_native_str(content_disposition)` which defaults to UTF-8 encoding. When the `content_disposition` bytes are encoded in non-UTF-8 encodings (like latin-1, gbk, cp720, iso2022_jp), the `to_unicode` function raises a `UnicodeDecodeError` (e.g., `'utf-8' codec can't decode byte 0xb5 in position 24: invalid start byte`). The method only catches `IndexError`, not `UnicodeDecodeError`, so the exception propagates up uncaught.

### Location
`scrapy/responsetypes.py`, lines 60-66, in the `from_content_disposition` method.

### Fix
```diff
--- a/scrapy/responsetypes.py
+++ b/scrapy/responsetypes.py
@@ -61,7 +61,11 @@ class ResponseTypes(object):
     def from_content_disposition(self, content_disposition):
         try:
-            filename = to_native_str(content_disposition).split(';')[1].split('=')[1]
+            try:
+                filename = to_native_str(content_disposition).split(';')[1].split('=')[1]
+            except UnicodeDecodeError:
+                filename = to_native_str(content_disposition, encoding='latin-1').split(';')[1].split('=')[1]
             filename = filename.strip('"\'')
             return self.from_filename(filename)
         except IndexError:
```

### Explanation
When `content_disposition` is encoded in a non-UTF-8 encoding, the initial `to_native_str` call with default UTF-8 encoding fails with `UnicodeDecodeError`. The fix catches this error and falls back to latin-1 decoding, which can decode any byte sequence without error. This allows the filename to be extracted from the Content-Disposition header regardless of the original encoding, and then `from_filename` can determine the appropriate response class based on the file extension. The KG shows the error path: `to_unicode` → `UnicodeDecodeError` when processing encodings like latin-1, gbk, cp720, and iso2022_jp.