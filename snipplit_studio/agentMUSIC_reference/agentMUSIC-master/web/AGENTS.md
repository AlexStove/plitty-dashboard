<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-15 | Updated: 2026-06-15 -->

# web

## Purpose
Source for the agentMUSIC dashboard — a React 18 + TypeScript single-page app built with Vite. It talks to the FastAPI backend (`api_server.py`) over `/api/*` and live `/api/events` (SSE), letting users import/upload tracks, pick choruses, launch generation jobs, watch progress, and browse rendered videos. The production build is written to the repo-root `static/` and served by FastAPI at `/dashboard`.

## Key Files
| File | Description |
|------|-------------|
| `package.json` | Dashboard manifest; scripts `dev` (Vite), `build` (`tsc -b && vite build`), `preview`. Pins Node 22.22.2. |
| `package-lock.json` | Locked dependency tree (`npm ci`). |
| `vite.config.ts` | Vite config — dev server, API proxy, build output to `static/`. |
| `tsconfig.json` / `tsconfig.node.json` | TypeScript project configs (app + Node/build context). |
| `index.html` | Vite HTML entry; mounts `src/main.tsx`. |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `src/` | Application source — components, hooks, API client, types, styles (see `src/AGENTS.md`) |
| `public/` | Static image assets copied verbatim into the build (POV-Spotify backgrounds/frames). No AGENTS.md — asset-only. |

## For AI Agents

### Working In This Directory
- Build output goes to the repo-root `static/` (not `web/dist`); FastAPI serves it at `/dashboard`. After UI changes, run `npm run build` so `static/` reflects them.
- Dev/build env vars live in `web/.env` (start from `web/.env.example`): `VITE_DEV_SERVER_PORT`, `VITE_API_PROXY_TARGET`, `VITE_MINIO_TRACKS_BUCKET`. Only `VITE_`-prefixed vars are exposed to the client.
- Keep TypeScript types in `src/types.ts` aligned with backend `modules/validation.py` (scenarios, orientations, request shapes) — they are the contract across the two halves.

### Testing Requirements
- No unit-test suite; the gate is a clean build: `npm ci && npm run build`, plus `npm audit --audit-level=moderate`. The `build` script runs `tsc -b` first, so type errors fail the build.

### Common Patterns
- Server state via TanStack React Query (`src/api/queries.ts`); local UI state via React hooks.
- Live updates via Server-Sent Events (`src/hooks/useSSE.ts`) rather than polling.
- Function components with explicit prop interfaces; one component per file.

## Dependencies

### Internal
- Consumes the FastAPI backend (`/api/*`, `/api/events`) defined in `api_server.py`.

### External
- React 18.3, react-dom, `@tanstack/react-query` 5.x (runtime); Vite 8, `@vitejs/plugin-react`, TypeScript 5.6, `@types/*` (dev).

<!-- MANUAL: -->
