# Legacy V2 Migration Notes

Last updated: 2026-03-19

## Purpose

This page keeps the older v2 migration guidance separate from the live schema reference in `docs/database/v2_schema.md`.

Treat the notes here as legacy migration context, not as current runtime instructions.

## Legacy Migration Assumptions

These notes describe the earlier v1-to-v2 transition model:
- table renames across webhook and backup tables
- column renames such as `transfer_type` -> `operation_type`, `process_id` -> `rsync_process_id`, and `backup_dir` -> `backup_path`
- index name updates to match renamed tables

## Legacy/Destructive Migration Guidance

Historical migration planning assumed data loss could be acceptable for the v2 cutover. That guidance may be destructive and should not be treated as the default for a live installation.

The older flow was:
- optionally back up the old database
- drop old tables
- create the new schema
- optionally migrate only critical data such as settings and active transfers

If you need that legacy path, review the script and validate it against the current deployment before using it.

## Current References

- Current live schema: `docs/database/v2_schema.md`
- Migration script reference: `scripts/migrate_v1_to_v2.py`
- Legacy v1 schema: `docs/database/v1_schema.md`
