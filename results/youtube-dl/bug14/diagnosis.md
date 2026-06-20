# CALL 1: Initial Analysis



I need to find the `_extract_chapters_from_description` method that should exist in the YoutubeIE class but doesn't. Let me request the relevant source code.

---

# CALL 2: Final Diagnosis (with additional code)

### Root Cause
The test calls `ie._extract_chapters_from_description(description, duration)` but the `YoutubeIE` class only has a static method named `_extract_chapters(description, duration)`, not `_extract_chapters_from_description`. The method name in the test doesn't match the actual method name defined in `youtube.py`.

### Location
`test/test_youtube_chapters.py`, line 271

### Fix
```diff
--- a/test/test_youtube_chapters.py
+++ b/test/test_youtube_chapters.py
@@ -268,5 +268,5 @@
         for description, duration, expected_chapters in self._TEST_CASES:
             ie = YoutubeIE()
             expect_value(
-                self, ie._extract_chapters_from_description(description, duration),
+                self, ie._extract_chapters(description, duration),
                 expected_chapters, None)
```

### Explanation
The KG shows an `AttributeError: 'YoutubeIE' object has no attribute '_extract_chapters_from_description'`. Looking at the `YoutubeIE` class in `youtube_dl/extractor/youtube.py`, the method is defined as `_extract_chapters(description, duration)` (a `@staticmethod`), not `_extract_chapters_from_description`. The test simply uses the wrong method name. Changing the call to `_extract_chapters` matches the actual method definition and resolves the error.