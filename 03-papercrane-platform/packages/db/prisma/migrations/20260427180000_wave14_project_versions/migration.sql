-- Paper Crane — Wave 14: project versioning + history
--
-- Adds an append-only snapshot table for projects. Every meaningful change to
-- a project (rename, description edit, hotspot save, default-params change,
-- explicit "save snapshot") writes one row here. Snapshots are immutable;
-- reverting creates a *new* version whose `snapshot` is a copy of the target
-- version, so revert itself shows up in history.
--
-- Schema decisions
-- ----------------
--   - `id` is text/cuid (matches Prisma `@default(cuid())`). The other ids
--     in the codebase are uuids, but versions are produced by the API layer
--     and benefit from short, copy-pasteable client-side ids — and there are
--     no Postgres triggers that need to default-generate one.
--   - `(project_id, version)` is unique to prevent gaps/dupes when two writers
--     race. The trpc `revert`/`save` mutation reads `MAX(version)` inside the
--     same transaction and bumps by 1; the unique constraint catches any race
--     and the caller retries.
--   - `snapshot` is JsonB and intentionally schemaless. The spec defines the
--     shape application-side; pinning it in the DB locks us out of cheap
--     additions later (e.g. `metadata.forkedFrom` on forks).
--   - Cascade on project delete: deleting a project nukes its versions. We
--     don't keep tombstones — the project itself is the audit anchor, and
--     the broader audit_logs table records the deletion event.
--
-- RLS
--   Versions inherit the parent project's tenancy. A user can SELECT/INSERT
--   only versions whose `project_id` belongs to a project in an org they're
--   a member of. There is intentionally NO update or delete policy: snapshots
--   are immutable, and project deletion cascades via FK rather than RLS.

CREATE TABLE "project_versions" (
  "id"          text             PRIMARY KEY,
  "project_id"  uuid             NOT NULL,
  "version"     integer          NOT NULL,
  "author_id"   uuid             NOT NULL,
  "description" text,
  "snapshot"    jsonb            NOT NULL,
  "created_at"  timestamptz(6)   NOT NULL DEFAULT now(),

  CONSTRAINT "project_versions_project_id_fkey"
    FOREIGN KEY ("project_id") REFERENCES "projects"("id")
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "project_versions_author_id_fkey"
    FOREIGN KEY ("author_id") REFERENCES "users"("id")
    ON DELETE NO ACTION ON UPDATE CASCADE,
  CONSTRAINT "project_versions_version_positive"
    CHECK ("version" >= 1)
);

CREATE UNIQUE INDEX "project_versions_project_id_version_key"
  ON "project_versions" ("project_id", "version");

CREATE INDEX "project_versions_project_id_created_at_idx"
  ON "project_versions" ("project_id", "created_at" DESC);

-- ── RLS ────────────────────────────────────────────────────────────────────
-- A user can see/insert versions for any project owned by an org they belong
-- to. The check joins through `projects` → `org_members` and uses the
-- `app_current_user()` helper installed by `00000000000000_enable_rls`.

ALTER TABLE "project_versions" ENABLE ROW LEVEL SECURITY;

CREATE POLICY "project_versions_member_select"
  ON "project_versions"
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
        FROM "projects" p
        JOIN "org_members" m
          ON m."org_id" = p."org_id"
       WHERE p."id" = "project_versions"."project_id"
         AND m."user_id" = app_current_user()
    )
  );

CREATE POLICY "project_versions_member_insert"
  ON "project_versions"
  FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1
        FROM "projects" p
        JOIN "org_members" m
          ON m."org_id" = p."org_id"
       WHERE p."id" = "project_versions"."project_id"
         AND m."user_id" = app_current_user()
    )
  );

-- No UPDATE or DELETE policy — versions are immutable. Project deletion
-- cascades through the FK and bypasses RLS via the service-role connection.
