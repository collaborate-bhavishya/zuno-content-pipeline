-- Lock down all pipeline tables with default-deny RLS.
--
-- RUN THIS ONLY AFTER swapping the backend's SUPABASE_KEY to the *secret* key
-- (sb_secret_...): secret keys bypass RLS, so backend writes keep working,
-- while the publishable key shipped to browsers loses all table access.
--
-- runs/questions already have RLS on (Supabase enables it on new tables by
-- default — the pipeline's inserts were failing against it). This makes the
-- state explicit and closes the remaining hole on image_assets.

-- Drop any pre-existing permissive policies first — enabling RLS alone is NOT
-- enough if an old "allow all" policy is attached (image_assets had one: the
-- publishable key could still read AND write it with RLS on).
do $$
declare p record;
begin
  for p in
    select policyname, tablename from pg_policies
    where schemaname = 'public'
      and tablename in ('image_assets', 'runs', 'questions')
  loop
    execute format('drop policy %I on public.%I', p.policyname, p.tablename);
  end loop;
end $$;

alter table image_assets enable row level security;
alter table runs enable row level security;
alter table questions enable row level security;

-- No policies remain: with RLS enabled and zero policies, anon and
-- authenticated roles are denied everything. Only the backend (secret key)
-- can read/write. Add narrow policies later only if the frontend ever needs
-- to query these tables directly instead of through the FastAPI backend.
