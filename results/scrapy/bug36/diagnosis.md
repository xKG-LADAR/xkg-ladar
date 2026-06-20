

### Root Cause
The test expects that when `from_settings` returns `None`, `create_instance` should raise a `TypeError`. However, the current `create_instance` implementation simply returns whatever `from_settings` returns (including `None`) without any type checking. The `AssertionError: TypeError not raised` in the KG confirms that `create_instance` returns `None` instead of raising `TypeError`.

### Location
`scrapy/utils/misc.py`, lines 147-150 (the return statements after calling constructors)

### Fix
```diff
--- a/scrapy/utils/misc.py
+++ b/scrapy/utils/misc.py
@@ -144,8 +144,14 @@ def create_instance(objcls, settings, crawler, *args, **kwargs):
         settings = crawler.settings
     if crawler and hasattr(objcls, 'from_crawler'):
-        return objcls.from_crawler(crawler, *args, **kwargs)
+        instance = objcls.from_crawler(crawler, *args, **kwargs)
+        if instance is None:
+            raise TypeError(f"{objcls.__qualname__}.from_crawler returned None")
+        return instance
     elif hasattr(objcls, 'from_settings'):
-        return objcls.from_settings(settings, *args, **kwargs)
+        instance = objcls.from_settings(settings, *args, **kwargs)
+        if instance is None:
+            raise TypeError(f"{objcls.__qualname__}.from_settings returned None")
+        return instance
     else:
         return objcls(*args, **kwargs)
```

### Explanation
The test sets `m.from_settings.return_value = None` and then expects `create_instance(m, settings, None)` to raise `TypeError`. The KG shows `AssertionError: TypeError not raised`, meaning `create_instance` silently returns `None` from `from_settings`. The fix adds validation that the `from_crawler` and `from_settings` constructors don't return `None`, raising `TypeError` if they do — which is a reasonable invariant since these factory methods should always return a valid instance.