### Root Cause
When `send()` is called with `to` as a single string (`'test@scrapy.org'`), `rcpts = to[:]` creates a copy of the string (not a list). Then `rcpts.extend(cc)` fails because strings don't have an `extend` method. The `send` method assumes `to` and `cc` are lists, but single string values should also be supported.

### Location
File: `scrapy/mail.py`, lines 56-59 (within the `send` method)

### Fix
```diff
--- a/scrapy/mail.py
+++ b/scrapy/mail.py
@@ -44,6 +44,10 @@
 
     def send(self, to, subject, body, cc=None, attachs=(), mimetype='text/plain', charset=None, _callback=None):
+        if isinstance(to, str):
+            to = [to]
+        if isinstance(cc, str):
+            cc = [cc]
         if attachs:
             msg = MIMEMultipart()
         else:
```

### Explanation
The test `test_send_single_values_to_and_cc` passes `to='test@scrapy.org'` and `cc='test@scrapy.org'` as strings. The `send` method then does `rcpts = to[:]` which on a string produces another string, and `rcpts.extend(cc)` fails with `AttributeError: 'str' object has no attribute 'extend'`. The fix normalizes `to` and `cc` to lists at the start of the method, so all downstream operations (`.join()`, `[:]`, `.extend()`) work correctly.