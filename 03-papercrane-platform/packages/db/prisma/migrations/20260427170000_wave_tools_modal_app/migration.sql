-- Wave: tools-API wiring — surface Modal deployment + closed-weights flag in catalog.
--
-- Adds two columns to `tools` so the public catalogue (tRPC `tools.list`) can
-- expose deployment-targetting and licensing flags directly without forcing the
-- ToolPicker UI to re-derive them from the JSONB `compute` blob.
--
--   modal_app      — `<workspace>/<name>@<version>` deployment reference. Null
--                    until the corresponding `tools/<slug>/modal_app.py` is
--                    deployed on Modal. The worker adapter throws a clear
--                    "Modal app not deployed for <slug>" error when null.
--   closed_weights — true for commercial-API / closed-weights tools (AlphaFold 3,
--                    proprietary forks). Drives the ToolPicker "Contact sales"
--                    overlay independently of `tier`.
--
-- Both default to safe values for existing rows so this migration is non-blocking.

ALTER TABLE "tools"
  ADD COLUMN "modal_app" TEXT,
  ADD COLUMN "closed_weights" BOOLEAN NOT NULL DEFAULT FALSE;
