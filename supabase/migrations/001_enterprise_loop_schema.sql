create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text unique not null,
  display_name text not null default '',
  role text not null default 'admin' check (role in ('admin', 'agent', 'qa_manager', 'knowledge_operator')),
  created_at timestamptz not null default now()
);

create table if not exists public.wecom_contacts (
  id uuid primary key default gen_random_uuid(),
  external_user_id text unique,
  wecom_user_id text,
  display_name text not null default '',
  channel text not null default 'wecom',
  raw_profile jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  channel text not null default 'internal',
  external_conversation_id text,
  customer_id uuid references public.wecom_contacts(id) on delete set null,
  customer_name text not null default '',
  customer_type text not null default '未知',
  status text not null default 'active' check (status in ('active', 'ai_replied', 'needs_human', 'resolved')),
  assigned_to uuid references public.profiles(id) on delete set null,
  last_message_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (channel, external_conversation_id)
);

create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  channel text not null default 'internal',
  direction text not null check (direction in ('inbound', 'outbound')),
  role text not null check (role in ('customer', 'assistant', 'human', 'system')),
  content text not null,
  raw_payload jsonb not null default '{}'::jsonb,
  wecom_msg_id text unique,
  dify_message_id text,
  delivery_status text not null default 'stored' check (delivery_status in ('stored', 'sent', 'failed')),
  created_at timestamptz not null default now()
);

create table if not exists public.ai_runs (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  trigger_message_id uuid references public.messages(id) on delete set null,
  dify_conversation_id text,
  dify_run_id text,
  input jsonb not null default '{}'::jsonb,
  output jsonb not null default '{}'::jsonb,
  decision text check (decision in ('send', 'retry', 'handoff', 'no_answer')),
  status text not null default 'pending' check (status in ('pending', 'succeeded', 'failed')),
  error text,
  latency_ms integer,
  created_at timestamptz not null default now()
);

create table if not exists public.qa_results (
  id uuid primary key default gen_random_uuid(),
  message_id uuid not null unique references public.messages(id) on delete cascade,
  ai_run_id uuid references public.ai_runs(id) on delete set null,
  accuracy integer not null check (accuracy between 1 and 5),
  completeness integer not null check (completeness between 1 and 5),
  professionalism integer not null check (professionalism between 1 and 5),
  empathy integer not null check (empathy between 1 and 5),
  efficiency integer not null check (efficiency between 1 and 5),
  overall_score numeric not null check (overall_score between 1 and 5),
  passed boolean not null default false,
  risk_level text not null default 'low' check (risk_level in ('low', 'medium', 'high')),
  reason text not null default '',
  evidence jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.knowledge_gaps (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid references public.conversations(id) on delete set null,
  message_id uuid references public.messages(id) on delete set null,
  question text not null,
  category text not null default '',
  priority text not null default 'medium' check (priority in ('low', 'medium', 'high')),
  frequency integer not null default 1,
  status text not null default 'open' check (status in ('open', 'drafted', 'added_to_kb', 'ignored')),
  suggested_answer text not null default '',
  created_by uuid references public.profiles(id) on delete set null,
  resolved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  actor_type text not null check (actor_type in ('system', 'admin', 'wecom', 'dify')),
  actor_id text,
  action text not null,
  target_type text not null,
  target_id uuid,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create unique index if not exists idx_profiles_email on public.profiles(email);
create unique index if not exists idx_wecom_contacts_external_user_id on public.wecom_contacts(external_user_id);
create unique index if not exists idx_conversations_channel_external on public.conversations(channel, external_conversation_id);
create index if not exists idx_conversations_status_last_message on public.conversations(status, last_message_at desc);
create index if not exists idx_conversations_customer_last_message on public.conversations(customer_id, last_message_at desc);
create index if not exists idx_messages_conversation_created on public.messages(conversation_id, created_at);
create unique index if not exists idx_messages_wecom_msg_id on public.messages(wecom_msg_id) where wecom_msg_id is not null;
create index if not exists idx_ai_runs_conversation_created on public.ai_runs(conversation_id, created_at desc);
create unique index if not exists idx_qa_results_message_id on public.qa_results(message_id);
create index if not exists idx_qa_results_created on public.qa_results(created_at desc);
create index if not exists idx_qa_results_passed_created on public.qa_results(passed, created_at desc);
create index if not exists idx_knowledge_gaps_status_priority_updated on public.knowledge_gaps(status, priority, updated_at desc);
create index if not exists idx_audit_logs_target_created on public.audit_logs(target_type, target_id, created_at desc);

alter table public.profiles enable row level security;
alter table public.wecom_contacts enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.ai_runs enable row level security;
alter table public.qa_results enable row level security;
alter table public.knowledge_gaps enable row level security;
alter table public.audit_logs enable row level security;

drop policy if exists "authenticated can read profiles" on public.profiles;
create policy "authenticated can read profiles" on public.profiles
  for select to authenticated using (true);

drop policy if exists "authenticated can read wecom contacts" on public.wecom_contacts;
create policy "authenticated can read wecom contacts" on public.wecom_contacts
  for select to authenticated using (true);

drop policy if exists "authenticated can read conversations" on public.conversations;
create policy "authenticated can read conversations" on public.conversations
  for select to authenticated using (true);

drop policy if exists "authenticated can update conversation status" on public.conversations;
create policy "authenticated can update conversation status" on public.conversations
  for update to authenticated using (true)
  with check (true);

drop policy if exists "authenticated can read messages" on public.messages;
create policy "authenticated can read messages" on public.messages
  for select to authenticated using (true);

drop policy if exists "authenticated can read ai runs" on public.ai_runs;
create policy "authenticated can read ai runs" on public.ai_runs
  for select to authenticated using (true);

drop policy if exists "authenticated can read qa results" on public.qa_results;
create policy "authenticated can read qa results" on public.qa_results
  for select to authenticated using (true);

drop policy if exists "authenticated can read knowledge gaps" on public.knowledge_gaps;
create policy "authenticated can read knowledge gaps" on public.knowledge_gaps
  for select to authenticated using (true);

drop policy if exists "authenticated can update knowledge gaps" on public.knowledge_gaps;
create policy "authenticated can update knowledge gaps" on public.knowledge_gaps
  for update to authenticated using (true)
  with check (true);

drop policy if exists "authenticated can read audit logs" on public.audit_logs;
create policy "authenticated can read audit logs" on public.audit_logs
  for select to authenticated using (true);
