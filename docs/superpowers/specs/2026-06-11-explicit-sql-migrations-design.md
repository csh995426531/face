# Explicit SQL Migrations Design

**Date:** 2026-06-11

## Goal

Replace startup-time schema mutation with an explicit migration command that executes a user-specified SQL file.

## Scope

- Add a migration runner command under `scripts/`.
- Add SQL migration files under `migrations/`.
- Remove schema-changing startup behavior from the API app.
- Keep runtime worker credential syncing separate from schema migration.

## Decisions

- Migration execution is explicit: `python -m scripts.migrate <sql-file>`.
- No migration history table is stored.
- SQL files are operator-selected and run in the order chosen by the operator.
- The runner stops on the first failing statement.

## Runtime Boundary

- Schema creation and alteration move to SQL files.
- API startup may still upsert runtime worker credentials, but it must not create or alter tables.

## Risks

- Without migration history, repeated execution safety depends on the SQL file content and operator discipline.
- MySQL DDL is not fully transactional, so partial application remains possible if a later statement fails.
