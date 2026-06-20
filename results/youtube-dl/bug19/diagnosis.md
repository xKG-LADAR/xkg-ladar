### Root Cause
The `expand_path` function in `utils.py` calls `os.path.expandvars()` on the filename, which expands shell variables like `$PATH` and `%PATH%` in the filename string. When the title contains `$PATH`, it gets expanded to the actual system PATH value instead of being kept as the literal string `$PATH`. The error message confirms this: `'Hello ' != 'Hello $PATH'`.

### Location
`youtube_dl/utils.py`, line 550 (the `expand_path` function)

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -546,4 +546,4 @@
 
 def expand_path(s):
     """Expand shell variables and ~"""
-    return os.path.expandvars(compat_expanduser(s))
+    return compat_expanduser(s)
```

### Explanation
The `expand_path` function is called on the already-formatted filename string in `prepare_filename`. At this point, user-provided metadata (like titles containing `$PATH` or `%PATH%`) has already been substituted into the template. Calling `os.path.expandvars()` then incorrectly expands these as environment variables. The fix removes `os.path.expandvars()` so that shell variables in user-provided metadata are preserved as literal strings. The `compat_expanduser()` call (which handles `~` expansion) is kept, as tilde expansion in paths is still desirable and doesn't conflict with user metadata.