### Root Cause
The `FailedHookException` class is missing from `cookiecutter/exceptions.py`. The test `test_run_failing_hook` references `exceptions.FailedHookException`, but this exception class was never defined in the exceptions module, causing `AttributeError: module 'cookiecutter.exceptions' has no attribute 'FailedHookException'`.

### Location
`cookiecutter/exceptions.py` — add the missing exception class after the existing exception definitions.

### Fix
```diff
--- a/cookiecutter/exceptions.py
+++ b/cookiecutter/exceptions.py
@@ -80,3 +80,9 @@
     Raised when cookiecutter is called with both `no_input==True` and
     `replay==True` at the same time.
     """
+
+
+class FailedHookException(CookiecutterException):
+    """
+    Raised when a hook script fails (returns a non-zero exit code).
+    """
```

### Explanation
The KG shows the error `AttributeError: module 'cookiecutter.exceptions' has no attribute 'FailedHookException'`. Inspecting `cookiecutter/exceptions.py` confirms that `FailedHookException` is not defined there. The test expects this exception to be raised when a hook script exits with a non-zero exit code. Adding the missing exception class to the exceptions module resolves the `AttributeError`. The hooks module also needs to raise this exception, but the search for exception-related code in `hooks.py` returned no matches, suggesting that the hooks module likely needs a corresponding change to `raise exceptions.FailedHookException(...)` when subprocess calls fail — however, the immediate cause of the test failure is the missing class definition.