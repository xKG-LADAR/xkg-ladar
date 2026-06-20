### Root Cause
The regex in `parse_duration` requires the `secs` group to match (it's not optional), so when the input is `'3 min'`, there's no seconds component and the regex fails to match, returning `None` instead of `180`. Similarly, `'2.5 hours'` would fail. The `secs` group and the overall structure need to be adjusted to allow durations with only minutes or only hours.

### Location
`youtube_dl/utils.py`, lines 1208-1222

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1207,16 +1207,22 @@ def parse_duration(s):
     m = re.match(
         r'''(?ix)T?
             (?:
-                (?:(?P<hours>[0-9]+)\s*(?:[:h]|hours?)\s*)?
-                (?P<mins>[0-9]+)\s*(?:[:m]|mins?|minutes?)\s*
+                (?:(?P<hours>[0-9.]+)\s*(?:[:h]|hours?)\s*)?
+                (?P<mins>[0-9.]+)\s*(?:[:m]|mins?|minutes?)\s*
             )?
-            (?P<secs>[0-9]+)(?P<ms>\.[0-9]+)?\s*(?:s|secs?|seconds?)?$''', s)
+            (?P<secs>[0-9]+)(?P<ms>\.[0-9]+)?\s*(?:s|secs?|seconds?)?$''', s)
     if not m:
-        return None
-    res = int(m.group('secs'))
-    if m.group('mins'):
-        res += int(m.group('mins')) * 60
-        if m.group('hours'):
-            res += int(m.group('hours')) * 60 * 60
+        m = re.match(
+            r'''(?ix)T?
+                (?:(?P<hours>[0-9.]+)\s*(?:[:h]|hours?)\s*)?
+                (?P<mins>[0-9.]+)\s*(?:[:m]|mins?|minutes?)\s*$''', s)
+        if not m:
+            return None
+    res = 0
+    if m.group('secs') if 'secs' in m.groupdict() and m.group('secs') else None:
+        res += int(m.group('secs'))
+    if m.group('mins') if 'mins' in m.groupdict() and m.group('mins') else None:
+        res += float(m.group('mins')) * 60
+    if m.group('hours') if 'hours' in m.groupdict() and m.group('hours') else None:
+        res += float(m.group('hours')) * 60 * 60
     if m.group('ms'):
         res += float(m.group('ms'))
     return res
```

Wait, let me reconsider for a cleaner fix:

```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1207,16 +1207,18 @@ def parse_duration(s):
     m = re.match(
         r'''(?ix)T?
             (?:
-                (?:(?P<hours>[0-9]+)\s*(?:[:h]|hours?)\s*)?
-                (?P<mins>[0-9]+)\s*(?:[:m]|mins?|minutes?)\s*
+                (?:(?P<hours>[0-9.]+)\s*(?:[:h]|hours?)\s*)?
+                (?P<mins>[0-9.]+)\s*(?:[:m]|mins?|minutes?)\s*
             )?
             (?P<secs>[0-9]+)(?P<ms>\.[0-9]+)?\s*(?:s|secs?|seconds?)?$''', s)
     if not m:
         return None
-    res = int(m.group('secs'))
+    res = 0
+    if m.group('secs'):
+        res += int(m.group('secs'))
     if m.group('mins'):
-        res += int(m.group('mins')) * 60
-        if m.group('hours'):
-            res += int(m.group('hours')) * 60 * 60
+        res += float(m.group('mins')) * 60
+    if m.group('hours'):
+        res += float(m.group('hours')) * 60 * 60
     if m.group('ms'):
         res += float(m.group('ms'))
     return res
```

Hmm, but this still requires `secs` to match since it's not optional in the regex. Let me provide the correct fix:

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1207,16 +1207,18 @@ def parse_duration(s):
     m = re.match(
         r'''(?ix)T?
             (?:
-                (?:(?P<hours>[0-9]+)\s*(?:[:h]|hours?)\s*)?
-                (?P<mins>[0-9]+)\s*(?:[:m]|mins?|minutes?)\s*
+                (?:(?P<hours>[0-9.]+)\s*(?:[:h]|hours?)\s*)?
+                (?P<mins>[0-9.]+)\s*(?:[:m]|mins?|minutes?)\s*
             )?
-            (?P<secs>[0-9]+)(?P<ms>\.[0-9]+)?\s*(?:s|secs?|seconds?)?$''', s)
+            (?:(?P<secs>[0-9]+)(?P<ms>\.[0-9]+)?\s*(?:s|secs?|seconds?)?)?$''', s)
     if not m:
         return None
-    res = int(m.group('secs'))
+    res = 0
+    if m.group('secs'):
+        res += int(m.group('secs'))
     if m.group('mins'):
-        res += int(m.group('mins')) * 60
-        if m.group('hours'):
-            res += int(m.group('hours')) * 60 * 60
+        res += float(m.group('mins')) * 60
+    if m.group('hours'):
+        res += float(m.group('hours')) * 60 * 60
     if m.group('ms'):
         res += float(m.group('ms'))
     return res
```

### Explanation
Three changes: (1) Made the `secs` group optional by wrapping it in `(?:...)?`, so inputs like `'3 min'` match with only the mins group. (2) Changed `int()` to `float()` for hours/mins parsing to support `'2.5 hours'`. (3) Un-nested the hours condition from mins, so hours can be parsed independently. The error `None != 180` occurred because `'3 min'` had no seconds component, causing the regex to fail entirely.