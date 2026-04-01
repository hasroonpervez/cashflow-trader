"""
Thread pools that attach Streamlit ScriptRunContext on worker startup.

Workers calling @st.cache_data (e.g. fetch_stock) need the context on their thread.
Streamlit recommends attaching before the worker runs meaningful code; using
ThreadPoolExecutor(initializer=...) runs once per worker thread at creation time.

See: streamlit.runtime.scriptrunner_utils.script_run_context.add_script_run_ctx
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor


def _scriptrunner_ctx_apis():
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import (
            add_script_run_ctx,
            get_script_run_ctx,
        )

        return get_script_run_ctx, add_script_run_ctx
    except Exception:
        pass
    try:
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

        return get_script_run_ctx, add_script_run_ctx
    except Exception:
        return None, None


def make_script_ctx_pool(max_workers: int) -> ThreadPoolExecutor:
    """ThreadPoolExecutor whose workers have ScriptRunContext attached from the first line of their lifetime."""
    get_ctx, add_ctx = _scriptrunner_ctx_apis()
    captured = get_ctx() if get_ctx else None

    def _initializer() -> None:
        if captured is not None and add_ctx is not None:
            add_ctx(threading.current_thread(), captured)

    return ThreadPoolExecutor(max_workers=max_workers, initializer=_initializer)


def submit_with_script_ctx(pool: ThreadPoolExecutor, fn, /, *args, **kwargs):
    """
    Submit fn(*args, **kwargs) on pool after re-attaching ScriptRunContext on the worker.

    Streamlit can clear thread-local context between cache layers; capturing ctx at submit
    time (main script thread) and calling add_script_run_ctx at task start avoids
    \"missing ScriptRunContext\" warnings from @st.cache_data inside workers.
    """
    get_ctx, add_ctx = _scriptrunner_ctx_apis()
    captured = get_ctx() if get_ctx else None

    def _run():
        if captured is not None and add_ctx is not None:
            add_ctx(threading.current_thread(), captured)
        return fn(*args, **kwargs)

    return pool.submit(_run)
