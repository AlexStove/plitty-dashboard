<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-15 | Updated: 2026-06-15 -->

# adr

## Purpose
Architecture Decision Records — short, dated Markdown documents capturing significant architectural choices and the reasoning behind them, so future contributors understand *why* the system is shaped the way it is.

## Key Files
| File | Description |
|------|-------------|
| `ADR-001-modular-monolith.md` | Decision to keep agentMUSIC as a single deployable process (bot + API + worker + repos) rather than splitting into microservices. |
| `ADR-002-file-backed-repositories.md` | Decision to persist tracks/choruses/videos as atomic JSON indexes instead of a database, keeping the read/write surface DB-swappable. |

## Subdirectories
None.

## For AI Agents

### Working In This Directory
- ADRs are append-only history. To revise a decision, add a new ADR that supersedes the old one (and note the supersession) — don't rewrite an accepted record.
- Use the next sequential number and the `ADR-NNN-short-title.md` naming convention.
- These records constrain backend design (e.g. ADR-002 is why `modules/*_db.py` use stable function APIs over `json_index.py`). Respect them when changing storage or deployment shape, or write a new ADR to change course.

### Testing Requirements
- None — documentation only.

### Common Patterns
- Standard ADR structure: context, decision, consequences.

## Dependencies

### Internal
- Decisions here describe constraints realized in `modules/` (repositories) and the root entry points (`bot.py`, `api_server.py`).

### External
- None.

<!-- MANUAL: -->
