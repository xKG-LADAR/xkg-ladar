### Root Cause
The `unified_strdate` function lacks the format `'%d/%m/%Y %H:%M:%S'` in its `format_expressions` list. The input `'28/01/2014 21:00:00'` (after timezone stripping) needs this format to be parsed correctly. The existing `'%d/%m/%Y'` format doesn't match because of the time component, and `'%Y/%m/%d %H:%M:%S'` doesn't match because the day/month/year order is reversed. This causes `upload_date` to remain `None`, leading to the `AssertionError: None != '20140128'`.

### Location
`youtube_dl/utils.py`, around line 891 (within the `format_expressions` list in `unified_strdate`)

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -889,6 +889,7 @@
         '%d.%m.%Y',
         '%d/%m/%Y',
         '%d/%m/%y',
+        '%d/%m/%Y %H:%M:%S',
         '%Y/%m/%d %H:%M:%S',
         '%Y-%m-%d %H:%M:%S',
         '%d.%m.%Y %H:%M',
```

### Explanation
The date string `'28/01/2014 21:00:00 +0100'` has its timezone offset stripped to become `'28/01/2014 21:00:00'`. None of the existing format expressions match this pattern — `'%d/%m/%Y'` fails because of the trailing time, and `'%Y/%m/%d %H:%M:%S'` fails because the components are in day/month/year order, not year/month/day. Adding `'%d/%m/%Y %H:%M:%S'` to the list allows this date string to be correctly parsed, producing `'20140128'`.