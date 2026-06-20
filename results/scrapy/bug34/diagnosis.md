### Root Cause

In `ItemMeta.__new__`, when a user defines `fields` as a dict attribute (e.g., `fields = {'new': Field(default='X')}`), the metaclass iterates over `dir(_class)` looking for `Field` instances as direct attributes. However, when `fields` is a dict containing `Field` instances (not individual class-level `Field` attributes), the metaclass overwrites `new_attrs['fields']` with an empty dict `{}` because no individual `Field` attributes are found via `dir(_class)`. The original `fields` dict from `attrs` is lost because the code doesn't merge user-provided `fields` dicts with discovered fields.

### Location

`scrapy/item.py`, lines 31-42 (the `__new__` method of `ItemMeta`)

### Fix

```diff
--- a/scrapy/item.py
+++ b/scrapy/item.py
@@ -29,6 +29,10 @@ class ItemMeta(ABCMeta):
         _class = super(ItemMeta, mcs).__new__(mcs, 'x_' + class_name, new_bases, attrs)
 
         fields = {}
+        # Inherit fields from base classes
+        for base in bases:
+            if hasattr(base, 'fields'):
+                fields.update(base.fields)
         new_attrs = {}
         for n in dir(_class):
             v = getattr(_class, n)
@@ -38,6 +42,10 @@ class ItemMeta(ABCMeta):
                 new_attrs[n] = attrs[n]
 
         new_attrs['fields'] = fields
+        # Merge in any explicitly defined 'fields' dict from the class body
+        if 'fields' in attrs and isinstance(attrs['fields'], dict):
+            for k, v in attrs['fields'].items():
+                new_attrs['fields'][k] = v
         new_attrs['_class'] = _class
         return super(ItemMeta, mcs).__new__(mcs, class_name, bases, new_attrs)
```

### Explanation

The bug occurs because when a user defines `fields = {'new': Field(default='X')}` in a class body, the metaclass's `__new__` method creates `_class` with those attrs, then iterates `dir(_class)` to find `Field` instances as class attributes. Since `'fields'` is a dict (not a `Field`), and `'new'` is a key inside that dict (not a class attribute), the field `'new'` is never discovered. The `fields` dict gets set to `{}`, and when `TestItem(new='New')` is called, `__setitem__` raises `KeyError` because `'new'` is not in `self.fields`.

The fix explicitly checks if the class body's `attrs` contains a `fields` dict and merges its entries into the computed fields. It also inherits fields from base classes to ensure proper field inheritance when `fields` is explicitly defined (which would otherwise shadow inherited fields).