alter table public.knowledge_items
  drop constraint if exists knowledge_items_item_type_check;

alter table public.knowledge_items
  add constraint knowledge_items_item_type_check
  check (item_type in ('product', 'policy', 'faq', 'store', 'contact'));

create index if not exists idx_knowledge_items_type_category_lifecycle
  on public.knowledge_items(item_type, category, lifecycle_status, updated_at desc);
