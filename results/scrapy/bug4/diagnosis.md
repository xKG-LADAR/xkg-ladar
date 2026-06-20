### Root Cause
In `eb_wrapper` (scrapy/contracts/__init__.py:87), the `exc_info` tuple is constructed with the wrong order: `failure.value, failure.type, failure.getTracebackObject()`. Python's `exc_info` format expects `(type, value, traceback)`, but here it's `(value, type, traceback)`. This causes an `AttributeError` because `results.addError` later tries to access `__traceback__` on `failure.type` (a class object) in the value position, but it's actually the exception type (a `getset_descriptor` has no `__traceback__`).

### Location
`scrapy/contracts/__init__.py`, line 87

### Fix
```diff
--- a/scrapy/contracts/__init__.py
+++ b/scrapy/contracts/__init__.py
@@ -84,7 +84,7 @@
 
         def eb_wrapper(failure):
             case = _create_testcase(method, 'errback')
-            exc_info = failure.value, failure.type, failure.getTracebackObject()
+            exc_info = failure.type, failure.value, failure.getTracebackObject()
             results.addError(case, exc_info)
 
         request.callback = cb_wrapper
```

### Explanation
Python's `sys.exc_info()` and `TestResult.addError` expect a 3-tuple of `(exc_type, exc_value, exc_traceback)`. The `eb_wrapper` function was constructing the tuple as `(failure.value, failure.type, failure.getTracebackObject())`, putting the exception instance first and the exception class second. This swapped order caused the `AttributeError: 'getset_descriptor' object has no attribute '__traceback__'` when the test framework tried to process the error info, expecting the second element to be the exception value with a `__traceback__` attribute. Swapping to `(failure.type, failure.value, ...)` matches the expected format.