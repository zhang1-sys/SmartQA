create table if not exists public.data_governance_policies (
  id uuid primary key default gen_random_uuid(),
  policy_key text not null unique,
  policy_name text not null,
  policy_type text not null check (policy_type in ('retention', 'masking', 'deletion', 'export')),
  scope text not null default 'global',
  config jsonb not null default '{}'::jsonb,
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.data_governance_policies enable row level security;

drop policy if exists "authenticated can read data governance policies" on public.data_governance_policies;
create policy "authenticated can read data governance policies" on public.data_governance_policies
  for select to authenticated using (true);

grant select on public.data_governance_policies to authenticated;
grant select, insert, update, delete on public.data_governance_policies to service_role;

insert into public.data_governance_policies (policy_key, policy_name, policy_type, scope, config, enabled)
values
  (
    'customer_pii_masking',
    '客户敏感信息脱敏',
    'masking',
    'messages,customer_profiles,customer_facts',
    '{"phone": true, "email": true, "address": true, "order_id": true, "show_last_digits": 4}'::jsonb,
    true
  ),
  (
    'conversation_retention',
    '会话数据保留周期',
    'retention',
    'conversations,messages,ai_runs,qa_results',
    '{"retention_days": 365, "archive_before_delete": true}'::jsonb,
    true
  ),
  (
    'audit_log_retention',
    '审计日志保留周期',
    'retention',
    'audit_logs',
    '{"retention_days": 730, "immutable": true}'::jsonb,
    true
  ),
  (
    'knowledge_version_retention',
    '知识版本保留策略',
    'retention',
    'knowledge_item_versions,knowledge_sync_jobs',
    '{"retain_all_published_versions": true, "sync_job_retention_days": 180}'::jsonb,
    true
  )
on conflict (policy_key) do update set
  policy_name = excluded.policy_name,
  policy_type = excluded.policy_type,
  scope = excluded.scope,
  config = excluded.config,
  enabled = excluded.enabled,
  updated_at = now();
