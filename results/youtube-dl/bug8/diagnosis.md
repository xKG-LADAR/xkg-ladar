

### Root Cause

The error `ValueError: '3gp' is not in list` occurs in `_sort_formats` within the `_formats_key` function. When a format has `vcodec` that is NOT `'none'` (i.e., it's a video format), the code tries to find `f['ext']` in `ORDER = ['webm', 'flv', 'mp4']`. The format with ext `'3gp'` is not in this list, causing a `ValueError`. While the KG shows this is caught, the real issue is in `_build_selector_function`: after the `elif selector.type == MERGE:` block, the code falls through to `filters = [self._build_format_filter(f) for f in selector.filters]` which tries to access `selector.filters`. But when `selector` is a `list` (from `_parse_format_selection` returning a list), the code at the end of `_build_selector_function` executes `filters = [self._build_format_filter(f) for f in selector.filters]` — but `selector` is a list which has no `.filters` attribute, causing `AttributeError: 'NoneType' object has no attribute 'type'`.

Looking more carefully at the KG, the `ERROR__AttributeError` is `'NoneType' object has no attribute 'type'`, which occurs in `_build_selector_function`. This happens when `_parse_format_selection` returns a list like `[FormatSelector(...), None]` due to the comma-separated format `'bestvideo/best,bestaudio'`. The issue is in `_parse_format_selection`: when processing `'/'`, it calls `_parse_format_selection(tokens, inside_choice=True)` which returns a list, and then sets `current_selector = None`. But the second choice list gets wrapped in `PICKFIRST`. The problem is that `second_choice` is a list `[FormatSelector(...)]`, and when building the `PICKFIRST` selector, it passes `(first_choice, second_choice)` where `second_choice` is already a list, making the tuple structure `(FormatSelector, [FormatSelector])`. In `_build_selector_function` for `PICKFIRST`, it iterates `selector.selector` expecting each element to be a `FormatSelector`, but `second_choice` is a list, so `s.type` fails when `s` is a list.

### Location

`youtube_dl/YoutubeDL.py`, in the `_build_selector_function` function within `build_format_selector`, around the `PICKFIRST` handling.

### Fix

```diff
--- a/youtube_dl/YoutubeDL.py
+++ b/youtube_dl/YoutubeDL.py
@@ -975,7 +975,10 @@ class YoutubeDL(object):
             elif selector.type == PICKFIRST:
                 fs = [_build_selector_function(s) for s in selector.selector]
 
                 def selector_function(formats):
                     for f in fs:
                         picked_formats = list(f(formats))
                         if picked_formats:
                             return picked_formats
                     return []
             elif selector.type == SINGLE:
```

Wait, let me re-examine. The `PICKFIRST` selector has `selector.selector = (first_choice, second_choice)` where `second_choice` is a list like `[FormatSelector(SINGLE, 'best', [])]`. When iterating `selector.selector`, `s` becomes first a `FormatSelector`, then a `list`. `_build_selector_function` handles lists at the top (`if isinstance(selector, list)`), so this should work. Let me look at what's actually `None`.

The `_parse_format_selection` for `'bestvideo/best,bestaudio'` with `inside_choice=True`: it parses `best`, then encounters `,`, and since `inside_choice=True`, it does `tokens.restore_last_token()` and breaks. So `second_choice = [FormatSelector(SINGLE, 'best', [])]`. Then `current_selector = None`, and the `,` triggers `selectors.append(current_selector)` — appending `None`. Then `bestaudio` is parsed. So `selectors` = `[FormatSelector(PICKFIRST,...), None, FormatSelector(SINGLE,'bestaudio',[])]`. The `None` causes the `AttributeError`.

```diff
--- a/youtube_dl/YoutubeDL.py
+++ b/youtube_dl/YoutubeDL.py
@@ -949,6 +949,8 @@ class YoutubeDL(object):
                     elif string == '/':
                         first_choice = current_selector
                         second_choice = _parse_format_selection(tokens, inside_choice=True)
+                        current_selector = FormatSelector(PICKFIRST, (first_choice, second_choice), [])
+                    elif string == ',' and inside_choice:
                         current_selector = None
-                        selectors.append(FormatSelector(PICKFIRST, (first_choice, second_choice), []))
+                        tokens.restore_last_token()
+                        break
                     elif string == '[':
```

Hmm, that's getting complex. Let me re-read the original code more carefully.

```diff
--- a/youtube_dl/YoutubeDL.py
+++ b/youtube_dl/YoutubeDL.py
@@ -948,8 +948,7 @@ class YoutubeDL(object):
                     elif string == '/':
                         first_choice = current_selector
                         second_choice = _parse_format_selection(tokens, inside_choice=True)
-                        current_selector = None
-                        selectors.append(FormatSelector(PICKFIRST, (first_choice, second_choice), []))
+                        current_selector = FormatSelector(PICKFIRST, (first_choice, second_choice), [])
                     elif string == '[':
                         if not current_selector:
                             current_selector = FormatSelector(SINGLE, 'best', [])
```

### Explanation

When parsing `'bestvideo/best,bestaudio'`, after processing `/`, the code sets `current_selector = None` and appends the `PICKFIRST` selector. Then when the `,` is encountered, it appends `current_selector` (which is `None`) to `selectors`, resulting in `[PICKFIRST_selector, None, bestaudio_selector]`. Later, `_build_selector_function` tries to access `None.type`, causing `AttributeError: 'NoneType' object has no attribute 'type'`. The fix keeps the `PICKFIRST` result as `current_selector` instead of immediately appending it, so when `,` is encountered, the non-None `current_selector` is properly appended, and a new `current_selector` cycle begins for `bestaudio`.