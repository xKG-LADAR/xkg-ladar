### Root Cause

The test `test_latin1_location` uses `self.assertEquals` which is a deprecated alias that has been removed in newer versions of Python's `unittest`. The KG shows `ERROR__AttributeError: 'RedirectMiddlewareTest' object has no attribute 'assertEquals'. Did you mean: 'assertEqual'?`. The test should use `self.assertEqual` instead.

### Location

File: `tests/test_downloadermiddleware_redirect.py`, line 166

### Fix

```diff
--- a/tests/test_downloadermiddleware_redirect.py
+++ b/tests/test_downloadermiddleware_redirect.py
@@ -164,7 +164,7 @@
         resp = Response('http://scrapytest.org/first', headers={'Location': latin1_location}, status=302)
         req_result = self.mw.process_response(req, resp, self.spider)
         perc_encoded_utf8_url = 'http://scrapytest.org/a%E7%E3o'
-        self.assertEquals(perc_encoded_utf8_url, req_result.url)
+        self.assertEqual(perc_encoded_utf8_url, req_result.url)
```

### Explanation

The KG clearly shows `ERROR__AttributeError: 'RedirectMiddlewareTest' object has no attribute 'assertEquals'. Did you mean: 'assertEqual'?` as a caught error in the test. The method `assertEquals` was a deprecated alias for `assertEqual` in Python's `unittest.TestCase` and has been removed in Python 3.12+. The fix is simply to use the canonical `assertEqual` method name.