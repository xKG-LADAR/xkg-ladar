### Root Cause
The `parse_iso8601` function fails when the date string contains fractional seconds (e.g., `'2014-03-23T22:04:26.1234Z'`). After stripping the timezone suffix `'Z'`, `date_str` becomes `'2014-03-23T22:04:26.1234'`, but `date_format` is `'%Y-%m-%dT%H:%M:%S'` which doesn't account for the fractional seconds part `.1234`. This causes `datetime.datetime.strptime` to raise `ValueError: unconverted data remains: .1234`.

### Location
`youtube_dl/utils.py`, lines 942-943 (between timezone parsing and `strptime` call)

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -940,6 +940,7 @@ def parse_iso8601(date_str, delimiter='T'):
                 hours=sign * int(m.group('hours')),
                 minutes=sign * int(m.group('minutes')))
     date_format =  '%Y-%m-%d{0}%H:%M:%S'.format(delimiter)
+    date_str = re.sub(r'\.\d+', '', date_str)
     dt = datetime.datetime.strptime(date_str, date_format) - timezone
     return calendar.timegm(dt.timetuple())
```

### Explanation
After stripping the timezone suffix but before parsing with `strptime`, we need to remove any fractional seconds (a dot followed by digits) from `date_str`. The KG shows that for input `'2014-03-23T22:04:26.1234Z'`, after timezone stripping `date_str` becomes `'2014-03-23T22:04:26.1234'`, and `strptime` with format `'%Y-%m-%dT%H:%M:%S'` raises `ValueError` on the `.1234` remainder. The fix strips the fractional seconds portion before calling `strptime`.