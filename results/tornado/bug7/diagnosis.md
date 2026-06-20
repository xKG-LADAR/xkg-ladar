# CALL 1: Initial Analysis



### Root Cause

The `run_in_executor` method at `tornado/ioloop.py:660` returns a `concurrent.futures.Future` directly from `executor.submit()`. When used with `await` in the `async_wrapper` function, a `concurrent.futures.Future` needs to be wrapped in an `asyncio`-compatible future. The raw `concurrent.futures.Future` is not directly awaitable in the way that works with Tornado's IOLoop, so it needs to be converted to a Tornado/asyncio `Future` that can be properly awaited.

### Location

`tornado/ioloop.py`, line 660 (the `return` statement of `run_in_executor`)

### Fix

```diff
--- a/tornado/ioloop.py
+++ b/tornado/ioloop.py
@@ -657,4 +657,5 @@ class IOLoop(Configurable):
             executor = self._executor
 
-        return executor.submit(func, *args)
+        c_future = executor.submit(func, *args)
+        return self.run_in_executor_future(c_future) if hasattr(self, 'run_in_executor_future') else self._wrap_executor_future(c_future)
```

Wait, let me look at this more carefully. The issue is that `executor.submit` returns a `concurrent.futures.Future` which is not an `asyncio.Future` and cannot be directly awaited with `await` in a native coroutine context. The fix should wrap it using `asyncio` or Tornado's future conversion.

### Fix

```diff
--- a/tornado/ioloop.py
+++ b/tornado/ioloop.py
@@ -642,6 +642,8 @@ class IOLoop(Configurable):
     def run_in_executor(self, executor, func, *args):
         """Runs a function in a ``concurrent.futures.Executor``. If
         ``executor`` is ``None``, the IO loop's default executor will be used.
 
         Use `functools.partial` to pass keyword arguments to `func`.
 
@@ -657,4 +659,6 @@ class IOLoop(Configurable):
             executor = self._executor
 
-        return executor.submit(func, *args)
+        c_future = executor.submit(func, *args)
+        # Wrap concurrent.futures.Future so it's compatible with await/yield.
+        t_future = self.add_future.__self__  # just need to convert
+        from tornado.concurrent import future_set_exc_info, chain_future
+        from concurrent.futures import Future as ConcurrentFuture
+        from tornado.gen import convert_yielded
+        return convert_yielded(c_future)
```

Hmm, let me reconsider. Let me look at what Tornado provides for this conversion.

---

# CALL 2: Final Diagnosis (with additional code)

### Root Cause

The `run_in_executor` method returns a raw `concurrent.futures.Future` from `executor.submit()`. When this is used with `await` in a native async coroutine (the `async_wrapper` function), the `concurrent.futures.Future` needs to be converted to a Tornado-compatible `Future` that can be properly yielded/awaited within Tornado's IOLoop. The raw `concurrent.futures.Future` is not properly integrated with Tornado's event loop, so the result never gets propagated back correctly.

### Location

`tornado/ioloop.py`, line 660 (the `return` statement of `run_in_executor`)

### Fix

```diff
--- a/tornado/ioloop.py
+++ b/tornado/ioloop.py
@@ -657,4 +657,7 @@ class IOLoop(Configurable):
             executor = self._executor
 
-        return executor.submit(func, *args)
+        c_future = executor.submit(func, *args)
+        # Wrap the concurrent.futures.Future into a Tornado Future
+        # so it works with both gen.coroutine (yield) and native coroutines (await).
+        t_future = TracebackFuture()
+        chain_future(c_future, t_future)
+        return t_future
```

### Explanation

The `executor.submit()` call returns a `concurrent.futures.Future`, which is not directly compatible with Tornado's IOLoop for use with `await` in native coroutines. The `chain_future` function (already imported in the module via `from tornado.concurrent import TracebackFuture, is_future` and available in `tornado/concurrent.py`) copies the result from one future to another. By creating a `TracebackFuture` (Tornado's Future) and chaining the concurrent future's result to it, we get a Tornado-compatible future that works with both `yield` (gen.coroutine) and `await` (native coroutines). The `chain_future` function is already defined in `tornado/concurrent.py` and needs to be imported.

```diff
--- a/tornado/ioloop.py
+++ b/tornado/ioloop.py
@@ -46,7 +46,7 @@ import time
 import traceback
 import math
 
-from tornado.concurrent import TracebackFuture, is_future
+from tornado.concurrent import TracebackFuture, is_future, chain_future
 from tornado.log import app_log, gen_log
 from tornado.platform.auto import set_close_exec, Waker
 from tornado import stack_context
@@ -657,4 +657,8 @@ class IOLoop(Configurable):
             executor = self._executor
 
-        return executor.submit(func, *args)
+        c_future = executor.submit(func, *args)
+        # Wrap the concurrent.futures.Future into a Tornado Future
+        # so it works with both gen.coroutine (yield) and native coroutines (await).
+        t_future = TracebackFuture()
+        chain_future(c_future, t_future)
+        return t_future
```