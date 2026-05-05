grant usage on schema public to anon, authenticated, service_role;

grant select on all tables in schema public to authenticated;
grant update on public.conversations, public.knowledge_gaps to authenticated;

grant select, insert, update, delete on all tables in schema public to service_role;

alter default privileges in schema public
  grant select on tables to authenticated;

alter default privileges in schema public
  grant select, insert, update, delete on tables to service_role;
