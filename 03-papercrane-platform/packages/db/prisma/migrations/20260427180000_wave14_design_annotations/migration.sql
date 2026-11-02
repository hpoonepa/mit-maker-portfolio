-- Paper Crane — Wave 14: design annotations, tags, stars
--
-- Lightweight collaboration layer on top of Designs:
--   1. design_annotations  — markdown comment thread
--   2. design_tags         — org-scoped, named/coloured chips (m2m via _DesignTags)
--   3. design_stars        — per-user save/star toggles
--
-- RLS
--   Annotations + stars piggy-back on the parent Design's RLS policy by joining
--   through `design_id`; the explicit policies below also key on
--   `app_current_org()` so a Design row produced by another tenant can never
--   leak via these tables. Tags carry their own org_id column for direct RLS.

-- ── design_annotations ─────────────────────────────────────────────────────

CREATE TABLE "design_annotations" (
  "id"         text                    PRIMARY KEY,
  "design_id"  uuid                    NOT NULL,
  "author_id"  uuid                    NOT NULL,
  "body"       text                    NOT NULL,
  "created_at" timestamptz(6)          NOT NULL DEFAULT now(),
  "updated_at" timestamptz(6)          NOT NULL DEFAULT now(),
  CONSTRAINT "design_annotations_design_id_fkey"
    FOREIGN KEY ("design_id") REFERENCES "designs"("id")
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "design_annotations_author_id_fkey"
    FOREIGN KEY ("author_id") REFERENCES "users"("id")
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX "design_annotations_design_id_created_at_idx"
  ON "design_annotations" ("design_id", "created_at" DESC);
CREATE INDEX "design_annotations_author_id_idx"
  ON "design_annotations" ("author_id");

-- ── design_tags ────────────────────────────────────────────────────────────

CREATE TABLE "design_tags" (
  "id"         text            PRIMARY KEY,
  "org_id"     uuid            NOT NULL,
  "name"       text            NOT NULL,
  "color"      text            NOT NULL,
  "created_at" timestamptz(6)  NOT NULL DEFAULT now(),
  CONSTRAINT "design_tags_org_id_fkey"
    FOREIGN KEY ("org_id") REFERENCES "organizations"("id")
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE UNIQUE INDEX "design_tags_org_id_name_key"
  ON "design_tags" ("org_id", "name");
CREATE INDEX "design_tags_org_id_idx"
  ON "design_tags" ("org_id");

-- Many-to-many join table (Prisma implicit relation `DesignTags`).
CREATE TABLE "_DesignTags" (
  "A" uuid NOT NULL,  -- Design.id
  "B" text NOT NULL,  -- DesignTag.id
  CONSTRAINT "_DesignTags_A_fkey"
    FOREIGN KEY ("A") REFERENCES "designs"("id")
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "_DesignTags_B_fkey"
    FOREIGN KEY ("B") REFERENCES "design_tags"("id")
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE UNIQUE INDEX "_DesignTags_AB_unique" ON "_DesignTags" ("A", "B");
CREATE INDEX "_DesignTags_B_index" ON "_DesignTags" ("B");

-- ── design_stars ───────────────────────────────────────────────────────────

CREATE TABLE "design_stars" (
  "design_id"  uuid            NOT NULL,
  "user_id"    uuid            NOT NULL,
  "starred_at" timestamptz(6)  NOT NULL DEFAULT now(),
  CONSTRAINT "design_stars_pkey" PRIMARY KEY ("design_id", "user_id"),
  CONSTRAINT "design_stars_design_id_fkey"
    FOREIGN KEY ("design_id") REFERENCES "designs"("id")
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "design_stars_user_id_fkey"
    FOREIGN KEY ("user_id") REFERENCES "users"("id")
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX "design_stars_user_id_starred_at_idx"
  ON "design_stars" ("user_id", "starred_at" DESC);

-- ── RLS ────────────────────────────────────────────────────────────────────
-- Depends on `app_current_user()` and `app_current_org()` from enable_rls.

ALTER TABLE "design_annotations" ENABLE ROW LEVEL SECURITY;
CREATE POLICY design_annotations_org_visibility ON "design_annotations"
  USING (EXISTS (
    SELECT 1 FROM "designs" d
    WHERE d.id = "design_annotations".design_id
      AND d.org_id = app_current_org()
  ));
CREATE POLICY design_annotations_self_insert ON "design_annotations"
  FOR INSERT WITH CHECK (
    author_id = app_current_user()
    AND EXISTS (
      SELECT 1 FROM "designs" d
      WHERE d.id = "design_annotations".design_id
        AND d.org_id = app_current_org()
    )
  );
CREATE POLICY design_annotations_self_update ON "design_annotations"
  FOR UPDATE USING (author_id = app_current_user());
CREATE POLICY design_annotations_self_delete ON "design_annotations"
  FOR DELETE USING (author_id = app_current_user());

ALTER TABLE "design_tags" ENABLE ROW LEVEL SECURITY;
CREATE POLICY design_tags_org_visibility ON "design_tags"
  USING (org_id = app_current_org());
CREATE POLICY design_tags_org_mutation ON "design_tags"
  FOR ALL USING (org_id = app_current_org())
  WITH CHECK (org_id = app_current_org());

ALTER TABLE "_DesignTags" ENABLE ROW LEVEL SECURITY;
CREATE POLICY design_tags_join_visibility ON "_DesignTags"
  USING (EXISTS (
    SELECT 1 FROM "designs" d
    WHERE d.id = "_DesignTags"."A" AND d.org_id = app_current_org()
  ));
CREATE POLICY design_tags_join_mutation ON "_DesignTags"
  FOR ALL USING (EXISTS (
    SELECT 1 FROM "designs" d
    WHERE d.id = "_DesignTags"."A" AND d.org_id = app_current_org()
  ))
  WITH CHECK (EXISTS (
    SELECT 1 FROM "designs" d
    WHERE d.id = "_DesignTags"."A" AND d.org_id = app_current_org()
  ));

ALTER TABLE "design_stars" ENABLE ROW LEVEL SECURITY;
CREATE POLICY design_stars_self_visibility ON "design_stars"
  USING (user_id = app_current_user());
CREATE POLICY design_stars_self_mutation ON "design_stars"
  FOR ALL USING (user_id = app_current_user())
  WITH CHECK (user_id = app_current_user());
