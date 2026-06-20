### Root Cause

The test expects that unary operators (`''` and `!`) on string-type values like `'title'` should check if the key exists in the dictionary and has a non-None value (for `''`) or is None/missing (for `!`). However, the current unary operator lambdas use `lambda v: v is not None` and `lambda v: v is None`, which means `!title` returns `True` when title is `None` (missing) but `False` when title is `''` (empty string). The test `self.assertFalse(match_str('!title', {'title': ''}))` fails because `'' is None` evaluates to `False`, so the `!` operator returns `False`, but the test also expects `self.assertTrue(match_str('title', {'title': ''}))` — wait, that passes since `'' is not None` is `True`.

Looking more carefully: `self.assertFalse(match_str('!title', {'title': ''}))` — `dct.get('title')` returns `''`, then `lambda v: v is None` gives `False`. So `match_str('!title', {'title': ''})` returns `False`. That's correct.

Let me re-examine: `self.assertTrue(match_str('is_live', {'is_live': False}))` — here `dct.get('is_live')` returns `False`, and `lambda v: v is not None` gives `True`. But the test expects `self.assertFalse(match_str('is_live', {'is_live': False}))`. This is the failing assertion — `True is not false`.

The unary `''` operator should treat `False` and `None` as falsy (key not meaningfully present), and `'!'` should be the inverse. The operators need to check truthiness, not just None-ness, for boolean values — but still return `True` for empty strings and `0`.

Looking at the expected behavior: `is_live=True` → `True`, `is_live=False` → `False`, `is_live=None` → `False`, `title=''` → `True`, `x=0` → `True`. So the check is: value is not None and value is not False.

### Location

`youtube_dl/utils.py`, lines 2575-2576 (the UNARY_OPERATORS lambdas in `_match_one`)

### Fix

```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -2573,8 +2573,8 @@ def _match_one(filter_part, dct):
 
     UNARY_OPERATORS = {
-        '': lambda v: v is not None,
-        '!': lambda v: v is None,
+        '': lambda v: (v is not None) if isinstance(v, compat_str) else v,
+        '!': lambda v: (v is None) if isinstance(v, compat_str) else (not v),
     }
     operator_rex = re.compile(r'''(?x)\s*
         (?P<op>%s)\s*(?P<key>[a-z_]+)
```

### Explanation

The original unary operators only checked `is not None` / `is None`. This meant `is_live=False` was treated as "present" (since `False is not None` is `True`), but the test expects it to be treated as falsy. The fix checks: for string values (`compat_str`), we only check against `None` (so empty strings like `title=''` still count as present). For non-string values (booleans, numbers, None), we use Python's truthiness, so `False`, `None`, and `0` are falsy while `True` and positive numbers are truthy. However, we also need `x=0` with `match_str('x', {'x': 0})` to return `True`. 

Let me re-check: `self.assertTrue(match_str('x', {'x': 0}))` — with the fix, `0` is not a `compat_str`, so `lambda v: v` returns `0` which is falsy. That would fail.

Let me reconsider: the distinction is between `False`/`None` (not present) vs everything else (present, including `0` and `''`).

```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -2573,8 +2573,8 @@ def _match_one(filter_part, dct):
 
     UNARY_OPERATORS = {
-        '': lambda v: v is not None,
-        '!': lambda v: v is None,
+        '': lambda v: v is not None and v is not False,
+        '!': lambda v: v is None or v is False,
     }
     operator_rex = re.compile(r'''(?x)\s*
         (?P<op>%s)\s*(?P<key>[a-z_]+)
```

This correctly handles all test cases: `is_live=False` → `False`, `is_live=None` → `False`, `is_live=True` → `True`, `x=0` → `True` (since `0 is not False`), `title=''` → `True` (since `'' is not False`), and missing keys → `False` (since `None`).