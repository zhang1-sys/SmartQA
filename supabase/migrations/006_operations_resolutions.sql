create table if not exists public.operations_resolutions (
  id uuid primary key default gen_random_uuid(),
  issue_type text not null check (issue_type in ('ai_run_failed', 'delivery_failed', 'knowledge_sync_job_failed', 'knowledge_item_sync_failed')),
  target_table text not null,
  target_id text not null,
  status text not null default 'active' check (status in ('active', 'reopened')),
  resolution_note text,
  resolved_by text not null default 'admin',
  resolved_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (issue_type, target_table, target_id)
);

create index if not exists idx_operations_resolutions_status
  on public.operations_resolutions(status, resolved_at desc);

create index if not exists idx_operations_resolutions_target
  on public.operations_resolutions(target_table, target_id);

alter table public.operations_resolutions enable row level security;

drop policy if exists "authenticated can read operations resolutions" on public.operations_resolutions;
create policy "authenticated can read operations resolutions" on public.operations_resolutions
for select to authenticated using (true);

grant select on public.operations_resolutions to authenticated;
grant select, insert, update, delete on public.operations_resolutions to service_role;
