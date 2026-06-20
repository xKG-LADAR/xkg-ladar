### Root Cause
The regex in `get_elements_by_attribute` fails to match `<div itemprop="author" itemscope>foo</div>` because the pattern for additional attributes after the target attribute requires `=` followed by a value (`=[a-zA-Z0-9:._-]*|="[^"]*"|='[^']*'`), but `itemscope` is a standalone boolean attribute with no value. The attribute pattern doesn't account for attributes without values.

### Location
File: `youtube_dl/utils.py`, lines 367-374 (the regex in `get_elements_by_attribute`)

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -367,10 +367,10 @@ def get_elements_by_attribute(attribute, value, html, escape_value=True):
     for m in re.finditer(r'''(?xs)
         <([a-zA-Z0-9:._-]+)
          (?:\s+[a-zA-Z0-9:._-]+(?:=[a-zA-Z0-9:._-]*|="[^"]*"|='[^']*'))*?
          \s+%s=['"]?%s['"]?
-         (?:\s+[a-zA-Z0-9:._-]+(?:=[a-zA-Z0-9:._-]*|="[^"]*"|='[^']*'))*?
+         (?:\s+[a-zA-Z0-9:._-]+(?:=[a-zA-Z0-9:._-]*|="[^"]*"|='[^']*')?)*?
         \s*>
         (?P<content>.*?)
         </\1>
     ''' % (re.escape(attribute), value), html):
         res = m.group('content')
```

### Explanation
The error `None != 'foo'` occurs because the regex doesn't match the `<div itemprop="author" itemscope>foo</div>` HTML. The attribute `itemscope` is a boolean attribute with no `=value` part. The second group of optional attributes (after the target attribute) requires `(?:=...)` but `itemscope` has no `=`. Making the `(?:=...)` part optional with `?` allows the regex to match boolean/standalone attributes, fixing the match for this case.