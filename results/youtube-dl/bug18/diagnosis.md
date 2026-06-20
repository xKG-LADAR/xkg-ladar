### Root Cause

In `process_ie_result`, when handling `url_transparent` results, the code builds `force_properties` from `ie_result` and then updates `new_result` with these properties. The problem is that `force_properties` includes **all** non-None values from `ie_result` (except `_type`, `url`, `ie_key`), including `id` and `extractor`/`extractor_key`. This means Foo1IE's `id: 'foo1_id'` overrides Foo3IE's `id: 'testid'`, and Foo1IE's `extractor`/`extractor_key` override Foo3IE's values. The test expects `id` to be `'testid'` but gets `'foo1_id'` because `force_properties` forces the outer `id` onto the inner result unconditionally.

The issue is that when the inner result (`info`) is itself a `url` type (which gets converted to `url_transparent`), the `force_properties` are propagated through recursive processing. The `extractor` and `extractor_key` from the outer IE should not override those set by the actual extracting IE. Specifically, the `force_properties` dict should not carry `extractor`, `extractor_key` since those get set by `add_default_extra_info` based on the actual IE that extracts.

### Location

`youtube_dl/YoutubeDL.py`, in the `process_ie_result` method, in the `url_transparent` handling block, around the `force_properties` construction.

### Fix

```diff
--- a/youtube_dl/YoutubeDL.py
+++ b/youtube_dl/YoutubeDL.py
@@ -862,7 +862,7 @@ class YoutubeDL(object):
             force_properties = dict(
                 (k, v) for k, v in ie_result.items() if v is not None)
-            for f in ('_type', 'url', 'ie_key'):
+            for f in ('_type', 'url', 'ie_key', 'extractor', 'extractor_key'):
                 if f in force_properties:
                     del force_properties[f]
             new_result = info.copy()
```

### Explanation

When processing a `url_transparent` result, the code copies properties from the outer result (`ie_result`) to the inner result (`new_result`). The `extractor` and `extractor_key` fields were being forcefully propagated from the outer IE (Foo1IE) to the inner result, overriding the values set by `add_default_extra_info` during the recursive `extract_info` call. By excluding `extractor` and `extractor_key` from `force_properties` (similar to how `_type`, `url`, and `ie_key` are already excluded), the actual extracting IE's metadata is preserved. This allows `downloaded['extractor']` to be `'testex'` and `downloaded['extractor_key']` to be `'TestEx'` as expected by the test, and also prevents `id` from being incorrectly overridden since the recursive processing will correctly handle the `id` from Foo3IE's result (`'testid'`).

Wait, let me re-examine. The `id: 'foo1_id'` is also in `force_properties` and overrides `'testid'`. But the test expects `id` to be `'testid'`. Looking more carefully at the KG: `ERROR__AssertionError: 'foo1_id' != 'testid'`. So `id` is also being incorrectly overridden.

The real issue is that when the inner `info` has `_type: 'url'`, which means it hasn't been fully resolved yet, the force_properties shouldn't override fields that will be set by the final extractor. The fix at line converting `_type: 'url'` to `_type: 'url_transparent'` should also ensure that only "display" fields like `title` are propagated, not identity fields like `id`. But looking at the test expectations: `title` should be `'foo1 title'` (from outer) but `id` should be `'testid'` (from inner). The distinction is that `id` should come from the final video, but `title` should be overridden by the transparent wrapper.

The proper fix should only force properties that are meant to be overridden by the transparent wrapper, not replace identity/source fields when the inner result is itself a URL that needs further resolution:

```diff
--- a/youtube_dl/YoutubeDL.py
+++ b/youtube_dl/YoutubeDL.py
@@ -862,7 +862,7 @@ class YoutubeDL(object):
 
             force_properties = dict(
                 (k, v) for k, v in ie_result.items() if v is not None)
-            for f in ('_type', 'url', 'ie_key'):
+            for f in ('_type', 'url', 'ie_key', 'id', 'extractor', 'extractor_key'):
                 if f in force_properties:
                     del force_properties[f]
             new_result = info.copy()
```