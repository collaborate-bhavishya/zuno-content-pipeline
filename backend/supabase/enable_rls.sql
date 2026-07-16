-- Lock down all pipeline tables with default-deny RLS.
--
-- RUN THIS ONLY AFTER swapping the backend's SUPABASE_KEY to the *secret* key
-- (sb_secret_...): secret keys bypass RLS, so backend writes keep working,
-- while the publishable key shipped to browsers loses all table access.
--
-- runs/questions already have RLS on (Supabase enables it on new tables by
-- default — the pipeline's inserts were failing against it). This makes the
-- state explicit and closes the remaining hole on image_assets.

alter table image_assets enable row level security;
alter table runs enable row level security;
alter table questions enable row level security;

-- No policies are created: with RLS enabled and zero policies, anon and
-- authenticated roles are denied everything. Only the backend (secret key)
-- can read/write. Add narrow policies later only if the frontend ever needs
-- to query these tables directly instead of through the FastAPI backend.
