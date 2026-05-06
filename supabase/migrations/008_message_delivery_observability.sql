alter table public.messages
  add column if not exists delivery_error text,
  add column if not exists delivered_at timestamptz;

create index if not exists idx_messages_delivery_status_created
  on public.messages(delivery_status, created_at desc);
