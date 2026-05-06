create table if not exists public.wecom_runtime_state (
  state_key text primary key,
  state_value text not null default '',
  metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create index if not exists idx_wecom_runtime_state_updated
  on public.wecom_runtime_state(updated_at desc);

alter table public.wecom_runtime_state enable row level security;

drop policy if exists "authenticated can read wecom runtime state" on public.wecom_runtime_state;
create policy "authenticated can read wecom runtime state" on public.wecom_runtime_state
  for select to authenticated using (true);

grant select on public.wecom_runtime_state to authenticated;
grant select, insert, update, delete on public.wecom_runtime_state to service_role;
