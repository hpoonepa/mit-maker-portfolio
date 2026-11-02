-- Wave 11: enable Supabase Realtime publication on tenant tables.
-- RLS (added in 20260427130000_apply_rls) already restricts each row to
-- members of its org, so realtime subscribers only receive their own rows.

DO $$
BEGIN
  -- jobs: status pill + per-job progress
  IF NOT EXISTS (
    SELECT 1
    FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime' AND schemaname = 'public' AND tablename = 'jobs'
  ) THEN
    EXECUTE 'ALTER PUBLICATION supabase_realtime ADD TABLE public.jobs';
  END IF;

  -- designs: stream new designs into the job page as the worker writes them
  IF NOT EXISTS (
    SELECT 1
    FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime' AND schemaname = 'public' AND tablename = 'designs'
  ) THEN
    EXECUTE 'ALTER PUBLICATION supabase_realtime ADD TABLE public.designs';
  END IF;

  -- notifications: global toast stream
  IF NOT EXISTS (
    SELECT 1
    FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime' AND schemaname = 'public' AND tablename = 'notifications'
  ) THEN
    EXECUTE 'ALTER PUBLICATION supabase_realtime ADD TABLE public.notifications';
  END IF;
END$$;

-- Ensure UPDATE payloads carry the full row so clients can diff status without
-- a follow-up fetch. (FULL is required for OLD-row delivery; without it
-- Supabase only sends primary keys for unchanged columns.)
ALTER TABLE public.jobs REPLICA IDENTITY FULL;
ALTER TABLE public.designs REPLICA IDENTITY FULL;
ALTER TABLE public.notifications REPLICA IDENTITY FULL;
