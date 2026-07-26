-- 0023_taxonomy_fields.sql
-- Laudon Ch.11 MEL taxonomy (C7): two new taxonomy dimensions that didn't exist as
-- either submission fields or audits columns before this migration --
-- evaluation_type (Baseline/Midline/Endline/Process evaluation/Impact evaluation/
-- Routine monitoring) and result_level (the logframe hierarchy: Output/Outcome/Impact).
-- sector/donor/org_type already exist as columns; this only adds the genuinely new ones.
-- See knowledge/taxonomy.yaml for the versioned reference list of valid values.
alter table audits add column if not exists evaluation_type text;
alter table audits add column if not exists result_level text;
