### Root Cause
The `initialize` method in `tornado/ioloop.py` has an inverted condition. When `make_current` is `True`, it raises `RuntimeError("current IOLoop already exists")` when `IOLoop.current(instance=False) is None` (i.e., when there is NO current IOLoop). The logic should be reversed: it should raise the error when a current IOLoop already EXISTS (i.e., when `IOLoop.current(instance=False) is not None`).

### Location
File: `tornado/ioloop.py`, in the `initialize` method (around line where `elif make_current:` branch is).

### Fix
```diff
--- a/tornado/ioloop.py
+++ b/tornado/ioloop.py
@@ -229,7 +229,7 @@ class IOLoop(Configurable):
         if make_current is None:
             if IOLoop.current(instance=False) is None:
                 self.make_current()
         elif make_current:
-            if IOLoop.current(instance=False) is None:
+            if IOLoop.current(instance=False) is not None:
                 raise RuntimeError("current IOLoop already exists")
             self.make_current()
```

### Explanation
The test `test_force_current` creates a first IOLoop with `make_current=True`, which should succeed (no current IOLoop exists yet). Then it creates a second IOLoop with `make_current=True`, which should fail because a current IOLoop already exists. 

With the buggy code, the condition `IOLoop.current(instance=False) is None` raises the error when there is *no* current IOLoop — exactly backwards. The first construction (when no IOLoop exists) would raise, and the second (when one already exists) would succeed. Changing `is None` to `is not None` corrects the logic so the error is raised only when a current IOLoop already exists.