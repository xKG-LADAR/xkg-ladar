### Root Cause
In `ItemMeta.__new__`, the `new_attrs` dictionary is built by iterating over `dir(_class)` and copying attributes from `attrs`. However, `__classcell__` is not returned by `dir()`, so it's never copied into `new_attrs`. When the second `super().__new__()` call creates the final class without `__classcell__`, Python 3.6+ raises a `TypeError` because the `__classcell__` must be propagated to `type.__new__` for classes that reference `__class__` (e.g., via `super()` or `__class__`).

### Location
`scrapy/item.py`, lines 33-42 (the `__new__` method of `ItemMeta`)

### Fix
```diff
--- a/scrapy/item.py
+++ b/scrapy/item.py
@@ -39,6 +39,8 @@ class ItemMeta(ABCMeta):
 
         new_attrs['fields'] = fields
         new_attrs['_class'] = _class
+        if '__classcell__' in attrs:
+            new_attrs['__classcell__'] = attrs['__classcell__']
         return super(ItemMeta, mcs).__new__(mcs, class_name, bases, new_attrs)
```

### Explanation
The `__classcell__` attribute is a special internal attribute in Python 3.6+ that must be passed through to `type.__new__` when a class body references `__class__` (which happens implicitly with `super()` or explicitly). Since `dir(_class)` does not include `__classcell__`, the loop that builds `new_attrs` never picks it up from `attrs`. The fix explicitly checks for `__classcell__` in `attrs` and propagates it to `new_attrs` before the final `super().__new__()` call, which matches the test's expectation that the second call includes `__classcell__` in its attrs.