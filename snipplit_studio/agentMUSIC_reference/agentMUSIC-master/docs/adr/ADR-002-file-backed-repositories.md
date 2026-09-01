# ADR-002: Use File-Backed Repositories Until Real Database Pressure Appears

## Status

Accepted

## Context

The app stores generated media on disk and keeps JSON indexes for tracks, choruses and videos. This is simple and matches the current deployment shape, but plain JSON files can be corrupted by interrupted writes.

## Decision

Keep JSON indexes for the current stage and make writes atomic through `modules/json_index.py`.

Do not introduce PostgreSQL or another database until there is a clear need: concurrent writes from multiple processes, advanced queries, multi-user permissions, audit trails or larger data retention requirements.

## Consequences

The current storage remains easy to inspect and back up.

Atomic writes reduce corruption risk.

The repository modules should keep their public functions stable so a database-backed implementation can replace them later.
