create table if not exists public.knowledge_items (
  id uuid primary key default gen_random_uuid(),
  item_type text not null check (item_type in ('product', 'policy', 'faq')),
  category text not null default '',
  title text not null,
  brand text not null default '',
  spec text not null default '',
  unit text not null default '',
  list_price numeric,
  wholesale_price numeric,
  wholesale_condition text not null default '',
  core_params text not null default '',
  usage_scenarios text not null default '',
  related_items text not null default '',
  question text not null default '',
  answer text not null default '',
  policy_scope text not null default '',
  policy_rule text not null default '',
  policy_timeframe text not null default '',
  policy_note text not null default '',
  lifecycle_status text not null default 'active' check (lifecycle_status in ('active', 'out_of_stock', 'inactive')),
  publish_status text not null default 'draft' check (publish_status in ('draft', 'published', 'archived')),
  sync_status text not null default 'pending' check (sync_status in ('pending', 'syncing', 'synced', 'failed')),
  dify_dataset_id text,
  dify_document_id text,
  last_sync_error text,
  last_synced_at timestamptz,
  created_by uuid references public.profiles(id) on delete set null,
  updated_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.knowledge_item_versions (
  id uuid primary key default gen_random_uuid(),
  knowledge_item_id uuid not null references public.knowledge_items(id) on delete cascade,
  version_number integer not null,
  snapshot jsonb not null default '{}'::jsonb,
  change_note text not null default '',
  created_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (knowledge_item_id, version_number)
);

create table if not exists public.knowledge_sync_jobs (
  id uuid primary key default gen_random_uuid(),
  knowledge_item_id uuid not null references public.knowledge_items(id) on delete cascade,
  provider text not null default 'dify' check (provider in ('dify')),
  operation text not null default 'upsert' check (operation in ('upsert', 'delete')),
  status text not null default 'pending' check (status in ('pending', 'running', 'succeeded', 'failed')),
  request_payload jsonb not null default '{}'::jsonb,
  response_payload jsonb not null default '{}'::jsonb,
  error text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_knowledge_items_type_status_updated
  on public.knowledge_items(item_type, publish_status, sync_status, updated_at desc);

create index if not exists idx_knowledge_items_category_title
  on public.knowledge_items(category, title);

create index if not exists idx_knowledge_sync_jobs_status_created
  on public.knowledge_sync_jobs(status, created_at desc);

create index if not exists idx_knowledge_sync_jobs_item_created
  on public.knowledge_sync_jobs(knowledge_item_id, created_at desc);

alter table public.knowledge_items enable row level security;
alter table public.knowledge_item_versions enable row level security;
alter table public.knowledge_sync_jobs enable row level security;

drop policy if exists "authenticated can read knowledge items" on public.knowledge_items;
create policy "authenticated can read knowledge items" on public.knowledge_items
  for select to authenticated using (true);

drop policy if exists "authenticated can read knowledge item versions" on public.knowledge_item_versions;
create policy "authenticated can read knowledge item versions" on public.knowledge_item_versions
  for select to authenticated using (true);

drop policy if exists "authenticated can read knowledge sync jobs" on public.knowledge_sync_jobs;
create policy "authenticated can read knowledge sync jobs" on public.knowledge_sync_jobs
  for select to authenticated using (true);

grant select on public.knowledge_items, public.knowledge_item_versions, public.knowledge_sync_jobs to authenticated;
grant select, insert, update, delete on public.knowledge_items, public.knowledge_item_versions, public.knowledge_sync_jobs to service_role;
