# Supabase 设置步骤

## 1. 创建项目

在 Supabase 创建新项目，记录：

- Project URL
- anon public key
- service role key

service role key 只能放在后端 `.env`，不要放到前端。

## 2. 执行数据库迁移

在 Supabase SQL Editor 执行：

```text
supabase/migrations/001_enterprise_loop_schema.sql
```

执行后应创建这些表：

- profiles
- wecom_contacts
- conversations
- messages
- ai_runs
- qa_results
- knowledge_gaps
- audit_logs

并启用 RLS。

## 3. 创建内部管理员账号

在 Supabase Auth 里创建一个内部管理员用户。

然后在 SQL Editor 执行：

```sql
insert into public.profiles (id, email, display_name, role)
select id, email, 'SmartQA Admin', 'admin'
from auth.users
where email = '你的管理员邮箱'
on conflict (id) do update
set email = excluded.email,
    display_name = excluded.display_name,
    role = excluded.role;
```

## 4. 配置本地 .env

复制 `.env.example` 为 `.env`，填入：

```text
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
INTERNAL_AUTH_REQUIRED=false
```

如果要让内部工作台必须登录，把 `INTERNAL_AUTH_REQUIRED` 改成：

```text
INTERNAL_AUTH_REQUIRED=true
```

前端登录页：

```text
http://localhost:5001/login.html
```

登录使用 Supabase Auth 邮箱密码。前端只使用 `SUPABASE_ANON_KEY` 调 Supabase Auth，业务写入仍由 Flask 后端使用 service role 完成。

重启 Flask 后访问：

```text
http://localhost:5001/api/system/health
```

确认：

```json
{
  "data_backend": "supabase",
  "supabase": {
    "ok": true
  }
}
```

## 5. 回滚说明

开发阶段可以直接删除 Supabase 项目或 drop 表重建。进入稳定演示后，不再直接 drop 业务表，改用新增 migration。
