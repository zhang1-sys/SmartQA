from __future__ import annotations

from services.sqlite_repository import SQLiteRepository
from services.supabase_repository import SupabaseRepository
from supabase_client import is_supabase_enabled, supabase


def get_repository():
    if is_supabase_enabled():
        return SupabaseRepository(supabase)
    return SQLiteRepository()
