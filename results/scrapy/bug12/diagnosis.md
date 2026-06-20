### Root Cause
The test uses `self.assertRaisesRegexp()` which was deprecated in Python 3.2 and removed in Python 3.12. The correct method name is `self.assertRaisesRegex()` (without the trailing 'p'). The `AttributeError` message confirms: `'SelectorTestCase' object has no attribute 'assertRaisesRegexp'. Did you mean: 'assertRaisesRegex'?`

### Location
`tests/test_selector.py`, line 127

### Fix
```diff
--- a/tests/test_selector.py
+++ b/tests/test_selector.py
@@ -124,7 +124,7 @@
 
     def test_selector_bad_args(self):
-        with self.assertRaisesRegexp(ValueError, 'received both response and text'):
+        with self.assertRaisesRegex(ValueError, 'received both response and text'):
             Selector(TextResponse(url='http://example.com', body=b''), text=u'')
```

### Explanation
`assertRaisesRegexp` was removed in newer versions of Python (3.12+). The KG shows the `AttributeError` is raised because the method doesn't exist on the test case object. The fix replaces it with the current API name `assertRaisesRegex`, which has been available since Python 3.2 and is the non-deprecated equivalent.