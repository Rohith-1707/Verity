-- VERITY schema for Supabase PostgreSQL. Writes go through the API; clients get read-only, org-scoped access via RLS.
-- Safe to re-run on a fresh project: it first removes any earlier partial attempt.
drop table if exists audit_logs, notifications, impacts, decisions, submission_versions, submissions, guidelines, document_versions, documents, profiles, organisations cascade;
drop function if exists public.app_org(); drop function if exists public.app_role();
drop function if exists public.current_org(); drop function if exists public.current_role();
create extension if not exists pgcrypto;
create table organisations (id uuid primary key default gen_random_uuid(), name text not null, created_at timestamptz default now());
create table profiles (id uuid primary key references auth.users on delete cascade, org_id uuid not null references organisations, display_name text not null,
  role text not null check (role in ('admin','creator','reviewer')), blocked boolean default false, created_at timestamptz default now());
create table documents (id uuid primary key default gen_random_uuid(), org_id uuid not null references organisations, title text not null, category text,
  created_by uuid references profiles, created_at timestamptz default now(), unique (org_id, title));
create table document_versions (id uuid primary key default gen_random_uuid(), document_id uuid not null references documents on delete cascade, org_id uuid not null,
  version text not null, effective_date date, review_date date, status text not null default 'approved' check (status in ('approved','superseded','archived')),
  storage_path text, body text not null, uploaded_by uuid references profiles, uploaded_at timestamptz default now());
create table guidelines (id uuid primary key default gen_random_uuid(), org_id uuid not null references organisations, kind text not null check (kind in ('banned','required')),
  value text not null, reason text, platform text default 'Any');
create table submissions (id uuid primary key default gen_random_uuid(), org_id uuid not null references organisations, creator_id uuid not null references profiles,
  title text not null, context jsonb not null, deadline date, status text not null default 'pending' check (status in ('pending','approved','revision','rejected')), created_at timestamptz default now());
create table submission_versions (id uuid primary key default gen_random_uuid(), submission_id uuid not null references submissions on delete cascade, org_id uuid not null,
  n int not null, body text not null, findings jsonb not null, risk jsonb not null, ai jsonb, created_at timestamptz default now(), unique (submission_id, n));
create table decisions (id uuid primary key default gen_random_uuid(), submission_id uuid not null references submissions on delete cascade, org_id uuid not null,
  reviewer_id uuid not null references profiles, version_n int not null, action text not null check (action in ('approved','revision','rejected')),
  genuineness text not null check (genuineness in ('Genuine','Misleading','Cannot determine')), comment text, created_at timestamptz default now());
create table impacts (id uuid primary key default gen_random_uuid(), org_id uuid not null, submission_id uuid not null references submissions on delete cascade,
  document_id uuid references documents, old_text text, sentence text, location text, status text default 'open' check (status in ('open','resolved')), created_at timestamptz default now());
create table notifications (id uuid primary key default gen_random_uuid(), org_id uuid not null, user_id uuid, role text, message text not null, read_by uuid[] default '{}', created_at timestamptz default now());
create table audit_logs (id uuid primary key default gen_random_uuid(), org_id uuid not null, actor_id uuid, action text not null, detail text, created_at timestamptz default now());
create index on submission_versions (submission_id); create index on document_versions (org_id, status); create index on audit_logs (org_id, created_at desc);

create function public.app_org() returns uuid language sql stable security definer set search_path = public as $$ select org_id from profiles where id = auth.uid() $$;
create function public.app_role() returns text language sql stable security definer set search_path = public as $$ select role from profiles where id = auth.uid() $$;
do $$ declare t text; begin
  foreach t in array array['organisations','profiles','documents','document_versions','guidelines','submissions','submission_versions','decisions','impacts','notifications','audit_logs'] loop
    execute format('alter table %I enable row level security', t); end loop; end $$;
create policy own_org on organisations for select using (id = app_org());
create policy own_profile on profiles for select using (org_id = app_org());
create policy org_read on documents for select using (org_id = app_org());
create policy org_read on document_versions for select using (org_id = app_org());
create policy org_read on guidelines for select using (org_id = app_org());
create policy org_read on submissions for select using (org_id = app_org() and (app_role() <> 'creator' or creator_id = auth.uid()));
create policy org_read on submission_versions for select using (org_id = app_org() and exists (select 1 from submissions s where s.id = submission_id));
create policy org_read on decisions for select using (org_id = app_org());
create policy org_read on impacts for select using (org_id = app_org() and app_role() <> 'creator');
create policy org_read on notifications for select using (org_id = app_org());
create policy admin_read on audit_logs for select using (org_id = app_org() and app_role() in ('admin','reviewer'));
-- No insert/update/delete policies: all writes use the API's server-side connection.
