# CALL 1: Initial Analysis



I need to understand the issue. The test `test_no_ref` creates a `WaitIterator` without keeping a reference to it, then calls `.next()` on it. The `WaitIterator` uses weak references internally, so if the `WaitIterator` gets garbage collected before the future completes, things break.

Let me look at the `WaitIterator.__init__` more carefully. The KG shows `waititerator_init_src` but it actually shows `Return.__init__`, not `WaitIterator.__init__`. Let me request the actual WaitIterator class.

---

# CALL 2: Final Diagnosis (with additional code)

### Root Cause

The `WaitIterator.__init__` source provided is actually `Return.__init__`, not the real `WaitIterator.__init__`. However, from the KG and the `_done_callback` method, we can see the issue: `WaitIterator` uses a weak reference (`self_ref`) in its `_done_callback`. When `test_no_ref` calls `gen.WaitIterator(gen.sleep(0)).next()`, there's no hard reference to the `WaitIterator` object. It can be garbage collected before `_done_callback` fires, making `self_ref()` return `None`, which means the result is never propagated to `_running_future`. The `with_timeout` then times out instead of completing successfully.

The fix should be in `_done_callback` or in the `next()` method to ensure the `WaitIterator` stays alive while a `_running_future` is pending. The most minimal fix is to capture a strong reference to `self` in `_running_future` so the `WaitIterator` stays alive while someone is waiting on `.next()`.

### Location

`tornado/gen.py` — in the `WaitIterator.next` method and/or `WaitIterator._done_callback` method.

### Fix

```diff
--- a/tornado/gen.py
+++ b/tornado/gen.py
@@ -350,6 +350,9 @@ class WaitIterator(object):
         """
         self._running_future = TracebackFuture()
 
+        # Keep a strong reference to self on the future to prevent GC
+        self._running_future._wait_iterator_ref = self
+
         if self._finished:
             self._return_result(self._finished.popleft())
 
```

### Explanation

The `WaitIterator` registers callbacks on input futures using a weak reference (`self_ref`) to allow GC when no one holds a reference. However, in `test_no_ref`, the pattern `gen.WaitIterator(gen.sleep(0)).next()` creates a `WaitIterator` with no hard reference — only the `Future` returned by `.next()` is kept. The `WaitIterator` gets garbage collected, `self_ref()` returns `None` in `_done_callback`, the result is never propagated to `_running_future`, and `with_timeout` eventually raises `TimeoutError`. By storing a strong reference to `self` on the `_running_future` object, the `WaitIterator` stays alive as long as someone holds a reference to the future returned by `.next()`, which is exactly the desired lifetime.