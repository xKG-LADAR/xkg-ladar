# CALL 1: Initial Analysis



I need to trace the flow of the `test_facebook_login` test to understand why it times out.

Let me look at the key path:

1. `test_facebook_login` fetches `/facebook/client/login?code=1234`
2. This triggers `_on_access_token` which parses the access token response
3. `_on_access_token` calls `self._oauth_get_user_future(access_token)` - but wait, this is `FacebookGraphMixin`, not `OAuthMixin`. Looking at the flow...
4. Actually for Facebook, `get_authenticated_user` calls `_on_access_token` at line 481
5. `_on_access_token` parses the response body and gets `access_token`
6. Then calls `facebook_request` which calls `oauth2_request`
7. `oauth2_request` passes `access_token` in `all_args`

Looking at the KG, `session` has `{'access_token': b'asdf', 'expires': None}` - note `access_token` is `b'asdf'` (bytes).

In `oauth2_request` (around line 660), `all_args["access_token"] = access_token` is set, then `url += "?" + urllib_parse.urlencode(all_args)`. The `kwargs` node shows `'access_token': b'asdf'` being passed to `facebook_request`.

Now looking at the `_on_oauth2_request` - it calls `json_decode(response.body)` on the response body `b'{}'`, which returns `{}`. Then `set_result({})` is called.

Looking at `_auth_future_to_callback`: it catches `AuthError` but the KG shows `ERROR__TypeError: "float() argument must be a string or a real number, not 'NoneType'"` being raised (caught) from `_set_done` → `_auth_future_to_callback`. 

Wait - the `_auth_future_to_callback` calls `callback(result)` where `callback` is the original callback. But looking more carefully at the Facebook flow, `_on_access_token` at line 481 is for `OAuthMixin`. For `FacebookGraphMixin`, there's a different `_on_access_token` - specifically for Facebook's `get_authenticated_user`.

Let me look at the `_on_access_token` shown: it calls `_oauth_get_user_future(access_token)` - but `FacebookGraphMixin` doesn't use OAuth1. The Facebook `get_authenticated_user` has its own callback chain. The result `{}` (empty dict) is returned as the user. When `_auth_future_to_callback` is called, `callback(result)` is called with `{}` - but the callback here expects to be the handler's callback which calls `self.finish()`. 

The timeout suggests the callback chain is broken. The `ERROR__TypeError` from `_set_done` → `_auth_future_to_callback` suggests `future.result()` raises a `TypeError`. But looking at the code, `_auth_future_to_callback` only catches `AuthError`, not `TypeError`. So the `TypeError` would propagate and be caught by `_set_done`'s exception handler, and the original callback never completes.

Looking at `_auth_future_to_callback`: `callback(result)` is called where `result = future.result()` which is `{}`. The `callback` here would be the handler's callback. But `TypeError: float() argument must be a string or a real number, not 'NoneType'` suggests something else. Given `session = {'access_token': b'asdf', 'expires': None}`, and if `callback` tries to do `float(None)` with `expires`, that's the issue.

But actually, looking more carefully at the `_on_access_token` for Facebook (line 481 in auth.py): it's the OAuthMixin version. Facebook's `get_authenticated_user` likely has its own `_on_access_token`. Let me check - the KG shows `_on_access_token` at `auth.py:481`. This is OAuthMixin's. But Facebook uses OAuth2, so it should have a different path.

---

# CALL 2: Final Diagnosis (with additional code)

### Root Cause

The `_on_access_token` method in `FacebookGraphMixin.get_authenticated_user` (around line 982) parses the access token response and creates a `session` dict with `session["access_token"]` being `b'asdf'` (bytes). It then passes `session["access_token"]` (bytes) as the `access_token` parameter to `facebook_request`. In `oauth2_request`, this bytes value gets passed through `urllib_parse.urlencode`, but the real issue is that `_on_get_user_info` eventually calls `future.set_result(fieldmap)` which includes `session.get("expires")` = `None`. When `_auth_future_to_callback` calls `callback(result)`, the callback is the handler's `finish` method. However, the `_auth_future_to_callback` encounters a `TypeError: float() argument must be a string or a real number, not 'NoneType'` which gets swallowed by `_set_done`'s exception handler, preventing the request from completing and causing the async test to time out.

Looking more carefully: `args["access_token"]` is `[b'asdf']` (a list from `parse_qs_bytes`), and `session["access_token"] = args["access_token"][-1]` gives `b'asdf'` (bytes). This bytes access token is passed to `facebook_request` which passes it to `oauth2_request`. The `_on_oauth2_request` callback receives the response `{}` and calls `future.set_result({})`. Then `_auth_future_to_callback` is called, which calls `callback(result)` where `callback` is actually `functools.partial(self._on_get_user_info, future, session, fields)`. The `_on_get_user_info` calls `future.set_result(fieldmap)`, triggering the outer `_auth_future_to_callback` which calls the handler's callback. But the `session["expires"]` is `args.get("expires")` which is `None` because the test server's access_token response is `access_token=asdf` with no expires field. This all works. The actual TypeError comes from trying to pass `b'asdf'` (bytes) as `access_token` to `facebook_request`/`oauth2_request` where it's used in URL encoding. Actually, the `session["access_token"]` is bytes `b'asdf'`, and this gets included in `fieldmap["access_token"]` and passed to `future.set_result()`, and eventually `_auth_future_to_callback` calls `callback(result)` which is `self.finish(user)`. The `self.finish()` with a dict should work fine.

Re-examining: the `_auth_future_to_callback` `TypeError` comes from a different path. The `_set_done` → `_auth_future_to_callback` error path shows `TypeError: float() argument must be a string or a real number, not 'NoneType'`. This happens when `get_async_test_timeout` returns `float(None)` because `os.environ.get('ASYNC_TEST_TIMEOUT')` returns `None`. But wait - the code catches `(ValueError, TypeError)` already. Let me re-read...

Actually no - looking at `get_async_test_timeout`, `os.environ.get('ASYNC_TEST_TIMEOUT')` returns `None` when unset, `float(None)` raises `TypeError`, which IS caught. So that's not the real issue.

The actual problem: `os.environ.get('ASYNC_TEST_TIMEOUT')` uses `get` on `os.environ`. But the KG shows `ERROR__KeyError: b'ASYNC_TEST_TIMEOUT'` - this suggests `os.environ` is being accessed with bytes key on Python 2, or the environment lookup uses bytes. The function catches `(ValueError, TypeError)` but NOT `KeyError`. If `os.environ[b'ASYNC_TEST_TIMEOUT']` raises `KeyError`, it's uncaught... but `.get()` shouldn't raise KeyError.

The real bug: The test times out because `_auth_future_to_callback` catches only `AuthError`, but a `TypeError` is raised during callback execution (from `_set_done`). This `TypeError` is logged but swallowed, breaking the callback chain.

Looking at `session["access_token"] = args["access_token"][-1]` where `args["access_token"]` is `[b'asdf']`. The `session["access_token"]` is `b'asdf'` (bytes). When passed to `facebook_request` as `access_token=session["access_token"]`, it flows to `oauth2_request` where `all_args["access_token"] = access_token` (bytes `b'asdf'`), then `url += "?" + urllib_parse.urlencode(all_args)`. The `fields` arg is a string. The URL gets constructed and the request is made. The response comes back as `{}`. Then `_on_get_user_info` is called with `user={}`. Since `user` is not `None`, it builds `fieldmap` with `user.get(field)` for each field (all `None`), plus `access_token=b'asdf'` and `session_expires=None`. Then `future.set_result(fieldmap)` triggers `_auth_future_to_callback(callback, future)` where `callback` is the handler. In `_auth_future_to_callback`, `result = future.result()` returns the fieldmap dict. Then `callback(result)` is called - the callback is `FacebookClientLoginHandler`'s callback which should call `self.finish(user)`.

Let me look at the test handler code more carefully.