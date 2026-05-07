alter table public.conversations
  add column if not exists lead_status text not null default 'new' check (lead_status in ('new', 'qualified', 'quoted', 'won', 'lost', 'nurture')),
  add column if not exists next_follow_up_at timestamptz,
  add column if not exists quotation_status text not null default 'none' check (quotation_status in ('none', 'needed', 'sent', 'accepted', 'rejected')),
  add column if not exists quotation_amount numeric,
  add column if not exists conversion_stage text not null default 'inquiry' check (conversion_stage in ('inquiry', 'needs_confirmed', 'quoted', 'won', 'lost'));

create index if not exists idx_conversations_lead_followup
  on public.conversations(lead_status, next_follow_up_at);

create index if not exists idx_conversations_conversion_stage
  on public.conversations(conversion_stage, updated_at desc);
