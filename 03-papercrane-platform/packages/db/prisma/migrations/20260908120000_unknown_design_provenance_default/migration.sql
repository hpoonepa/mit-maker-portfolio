-- Change future inserts only. Existing 'real' values cannot be distinguished
-- from the historical default without execution evidence; audit separately.
ALTER TABLE "designs" ALTER COLUMN "provenance" SET DEFAULT 'unknown';
