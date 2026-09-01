# ADR-001: Keep agentMUSIC as a Modular Monolith

## Status

Accepted

## Context

agentMUSIC has one deployable process that combines the Telegram bot, FastAPI API, a local worker queue and file-backed repositories. Splitting this into separate services would add deployment, networking and operational complexity before the app has clear independent scaling boundaries.

## Decision

Keep the application as a modular monolith for now.

Shared cross-cutting concerns are centralized under `modules/`:

- configuration via environment variables;
- structured API errors;
- request validation;
- repository helpers;
- background job tracking.

Domain code should be split gradually by behavior: tracks, choruses, videos, jobs and generation.

## Consequences

One process remains easy to run locally and deploy.

The codebase gets clearer module boundaries without introducing service-to-service calls.

Future extraction is still possible if generation workers, media storage or API traffic need separate scaling.
