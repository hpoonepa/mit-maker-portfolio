-- Paper Crane — Add app_current_org() helper for RLS policies
--
-- Wave 14 (design annotations) and Wave 15 (feedback) introduced policies that
-- key off `app_current_org()`, but only `app_current_user()` was defined in
-- the original `apply_rls` migration. Adding the missing helper here so
-- subsequent migrations can reference it.
--
-- The function reads the per-request session GUC `app.current_org` set by
-- the API server's `withRls()` wrapper (mirrors `app.current_user`). When
-- unset, returns NULL — RLS policies that USE (org_id = app_current_org())
-- evaluate to NULL → false, so callers without a session see nothing.

CREATE OR REPLACE FUNCTION app_current_org() RETURNS uuid AS $$
  SELECT NULLIF(current_setting('app.current_org', true), '')::uuid
$$ LANGUAGE sql STABLE SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION app_current_org() TO PUBLIC;
