"""Supabase client.

Uses the service key, so this bypasses RLS. It must never be importable from
anything the browser reaches. RLS stays enabled as defence in depth, but the
real access control is that every write goes through a FastAPI route that has
already checked who is asking.
"""

from functools import lru_cache

from supabase import Client, create_client

from .config import settings


@lru_cache(maxsize=1)
def db() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_key)
