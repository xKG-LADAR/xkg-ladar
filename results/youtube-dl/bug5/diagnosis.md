### Root Cause

The `timetuple` variable returned by `email.utils.parsedate_tz(date_str)` is a plain tuple, not a `datetime` object. The code on line 1118 calls `timetuple.timetuple()` which raises `AttributeError: 'tuple' object has no attribute 'timetuple'`. The correct function to convert the result of `parsedate_tz` to a timestamp is `email.utils.mktime_tz(timetuple)`, not `calendar.timegm(timetuple.timetuple())`.

### Location

`youtube_dl/utils.py`, line 1118

### Fix

```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1115,7 +1115,7 @@ def unified_timestamp(date_str, day_first=True):
         except ValueError:
             pass
     timetuple = email.utils.parsedate_tz(date_str)
     if timetuple:
-        return calendar.timegm(timetuple.timetuple())
+        return calendar.timegm(email.utils.mktime_tz(timetuple))
```

### Explanation

`email.utils.parsedate_tz()` returns a 10-tuple (not a datetime object), so calling `.timetuple()` on it raises an `AttributeError`. The KG confirms this: `timetuple` has value `(2016, 5, 16, 11, 15, 0, 0, 1, -1, 0)` and the error is `AttributeError: 'tuple' object has no attribute 'timetuple'`. The fix uses `email.utils.mktime_tz()` which correctly converts the `parsedate_tz` tuple to a UTC timestamp, then passes that to `calendar.timegm()`. However, `mktime_tz` already returns a Unix timestamp integer, so wrapping it in `calendar.timegm` would be incorrect. Let me correct:

```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1115,7 +1115,7 @@ def unified_timestamp(date_str, day_first=True):
         except ValueError:
             pass
     timetuple = email.utils.parsedate_tz(date_str)
     if timetuple:
-        return calendar.timegm(timetuple.timetuple())
+        return email.utils.mktime_tz(timetuple)
```

`email.utils.mktime_tz()` directly returns the Unix timestamp as an integer, properly handling the timezone offset in the tuple, which is exactly what `unified_timestamp` should return.