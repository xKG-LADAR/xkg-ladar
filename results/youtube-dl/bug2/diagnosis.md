### Root Cause

The test expects 7 formats but only 6 are returned. The KG shows that `existing_format` is written twice — once for audio format_id '318597' and once for video format_id '318597'. Since both adaptation sets have a representation with id '318597', the second one (video) updates the first (audio) via `existing_format.update(f)` instead of being added as a new format. The duplicate detection logic matches on `format_id == representation_id` without considering that different content types (audio vs video) should be treated as separate formats.

### Location

`youtube_dl/extractor/common.py`, around line 1929 (the `try/except StopIteration` block where duplicate format_id detection occurs).

### Fix

```diff
--- a/youtube_dl/extractor/common.py
+++ b/youtube_dl/extractor/common.py
@@ -1926,7 +1926,8 @@ class InfoExtractor(object):
                         try:
                             existing_format = next(
                                 fo for fo in formats
-                                if fo['format_id'] == representation_id)
+                                if fo['format_id'] == representation_id
+                                and fo.get('format_note') == 'DASH %s' % content_type)
                         except StopIteration:
                             full_info = formats_dict.get(representation_id, {}).copy()
                             full_info.update(f)
```

### Explanation

The bug occurs because two representations in different AdaptationSets (one audio, one video) share the same `representation_id` ('318597'). The existing duplicate detection only checks `format_id == representation_id`, so when the video representation with id '318597' is processed, it finds the already-added audio format with the same id and updates it in place, rather than adding a new entry. This results in 6 formats instead of the expected 7. The fix adds a check on `format_note` (which encodes the content type as 'DASH audio' or 'DASH video') so that formats of different content types are not considered duplicates even if they share the same representation id.