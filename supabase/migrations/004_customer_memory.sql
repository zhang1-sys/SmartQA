create table if not exists public.customer_profiles (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid references public.wecom_contacts(id) on delete set null,
  channel text not null default '',
  external_customer_key text not null,
  display_name text not null default '',
  company_name text not null default '',
  city text not null default '',
  customer_type text not null default '',
  lifecycle_stage text not null default 'unknown' check (lifecycle_stage in ('unknown', 'lead', 'prospect', 'active_customer', 'at_risk', 'inactive')),
  preference_summary text not null default '',
  risk_notes text not null default '',
  last_intent text not null default '',
  last_product_interest text not null default '',
  last_contacted_at timestamptz,
  first_seen_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (channel, external_customer_key)
);

create table if not exists public.customer_facts (
  id uuid primary key default gen_random_uuid(),
  customer_profile_id uuid not null references public.customer_profiles(id) on delete cascade,
  fact_type text not null check (fact_type in ('city', 'product_interest', 'spec_requirement', 'budget_signal', 'project_context', 'preference', 'risk', 'contact_info')),
  fact_key text not null,
  fact_value text not null,
  confidence numeric not null default 0.7 check (confidence between 0 and 1),
  source_conversation_id uuid references public.conversations(id) on delete set null,
  source_message_id uuid references public.messages(id) on delete set null,
  last_seen_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (customer_profile_id, fact_type, fact_key)
);

create table if not exists public.conversation_summaries (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null unique references public.conversations(id) on delete cascade,
  customer_profile_id uuid references public.customer_profiles(id) on delete set null,
  summary text not null default '',
  open_questions text not null default '',
  last_intent text not null default '',
  last_product_interest text not null default '',
  last_decision text not null default '',
  turn_count integer not null default 0,
  updated_at timestamptz not null default now()
);

create index if not exists idx_customer_profiles_customer_updated
  on public.customer_profiles(customer_id, updated_at desc);

create index if not exists idx_customer_profiles_channel_updated
  on public.customer_profiles(channel, updated_at desc);

create index if not exists idx_customer_facts_profile_seen
  on public.customer_facts(customer_profile_id, last_seen_at desc);

create index if not exists idx_customer_facts_type_value
  on public.customer_facts(fact_type, fact_value);

create index if not exists idx_conversation_summaries_profile_updated
  on public.conversation_summaries(customer_profile_id, updated_at desc);

alter table public.customer_profiles enable row level security;
alter table public.customer_facts enable row level security;
alter table public.conversation_summaries enable row level security;

drop policy if exists "authenticated can read customer profiles" on public.customer_profiles;
create policy "authenticated can read customer profiles" on public.customer_profiles
  for select to authenticated using (true);

drop policy if exists "authenticated can read customer facts" on public.customer_facts;
create policy "authenticated can read customer facts" on public.customer_facts
  for select to authenticated using (true);

drop policy if exists "authenticated can read conversation summaries" on public.conversation_summaries;
create policy "authenticated can read conversation summaries" on public.conversation_summaries
  for select to authenticated using (true);

grant select on public.customer_profiles, public.customer_facts, public.conversation_summaries to authenticated;
grant select, insert, update, delete on public.customer_profiles, public.customer_facts, public.conversation_summaries to service_role;
