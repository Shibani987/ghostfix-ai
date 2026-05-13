from __future__ import annotations

import warnings
from typing import Any

from utils.env import SUPABASE_KEY, SUPABASE_URL

warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"supabase(\.|$)")
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"postgrest(\.|$)")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=r"The 'timeout' parameter is deprecated.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=r"The 'verify' parameter is deprecated.*")

_client = None
_client_attempted = False
_unavailable_reason = ""


def training_memory_available() -> bool:
    return _get_client() is not None


def training_memory_status() -> dict[str, Any]:
    client = _get_client()
    return {
        "available": client is not None,
        "mode": "cloud" if client is not None else "local-only",
        "reason": "" if client is not None else (_unavailable_reason or "Supabase is not configured."),
    }


def save_training_data(data: dict):
    client = _get_client()
    if client is None:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return client.table("ghostfix_training_data").insert(data).execute()


def search_training_data(limit: int = 10000, batch_size: int = 1000, *, verbose: bool = False):
    """Fetch optional cloud training rows when Supabase is configured."""
    client = _get_client()
    if client is None:
        if verbose and _unavailable_reason:
            print(f"Cloud training memory unavailable: {_unavailable_reason}")
        return []

    all_data = []
    start = 0
    while len(all_data) < limit:
        end = start + batch_size - 1
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            res = (
                client
                .table("ghostfix_training_data")
                .select("*")
                .range(start, end)
                .execute()
            )
        rows = res.data or []
        if not rows:
            break
        all_data.extend(rows)
        if verbose:
            print(f"Fetched {len(all_data)} rows...")
        if len(rows) < batch_size:
            break
        start += batch_size
    return all_data[:limit]


def _get_client():
    global _client, _client_attempted, _unavailable_reason
    if _client_attempted:
        return _client
    _client_attempted = True
    if not SUPABASE_URL or not SUPABASE_KEY:
        _unavailable_reason = "SUPABASE_URL/SUPABASE_KEY are not set; staying in local-only mode."
        return None
    try:
        from supabase import create_client
    except Exception as exc:
        _unavailable_reason = f"Optional dependency 'supabase' is not installed: {exc}"
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as exc:
        _unavailable_reason = f"Supabase client could not be created: {exc}"
        _client = None
    return _client
