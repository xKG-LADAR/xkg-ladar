### Root Cause
The test `test_generate_context_decodes_non_ascii_chars` expects a file at `tests/test-generate-context/non_ascii.json`, but the directory listing of `tests/test-generate-context/` shows no such file exists. The `FileNotFoundError` is raised because the test fixture file `non_ascii.json` is missing from the `tests/test-generate-context/` directory.

### Location
File: `tests/test-generate-context/non_ascii.json` (needs to be created)

### Fix
```diff
--- /dev/null
+++ b/tests/test-generate-context/non_ascii.json
@@ -0,0 +1,3 @@
+{
+    "full_name": "éèà"
+}
```

### Explanation
The KG shows a `FileNotFoundError: [Errno 2] No such file or directory: 'tests/test-generate-context/non_ascii.json'` when `generate_context` tries to `open(context_file)`. The directory listing confirms the file doesn't exist — only `choices_template.json`, `invalid-syntax.json`, and `test.json` are present. The test expects `generate_context` to return `{'non_ascii': OrderedDict([('full_name', 'éèà')])}`, so the JSON file needs to contain `{"full_name": "éèà"}`. The key `non_ascii` is derived from the filename stem (`non_ascii.json` → `non_ascii`) by the `generate_context` function.