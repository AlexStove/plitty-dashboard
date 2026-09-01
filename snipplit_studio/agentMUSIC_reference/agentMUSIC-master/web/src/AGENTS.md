<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-15 | Updated: 2026-06-15 -->

# src

## Purpose
The React + TypeScript application code for the dashboard. `App.tsx` composes the whole UI; data flows in through React Query hooks (`api/`) and live SSE updates (`hooks/`), and out through mutations. Shared TypeScript types in `types.ts` form the contract with the FastAPI backend.

## Key Files
| File | Description |
|------|-------------|
| `main.tsx` | App bootstrap — mounts `<App>` and sets up the React Query client. |
| `App.tsx` | Root component. Wires queries (`useStats/useJobs/useChoruses/useVideos`), live events (`useLiveEvents`), and toast state; lays out Header → VinylDisc → SourceTabs → GeneratePanel/ChorusesPanel → JobsPanel → VideosGrid → VideoModal. |
| `types.ts` | Shared interfaces/enums: `Stats`, `Job`, `Chorus`, `Video`, `MinioTrack`, `GenerateParams`, `LiveEvent`, and the `Scenario`/`BgType`/`Orientation`/`TabId` unions. |
| `styles.css` | Global dashboard styles (layout classes like `bottom-section`, `grid2`). |
| `vite-env.d.ts` | Vite/TypeScript ambient type declarations. |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `components/` | Feature and chrome UI components (see `components/AGENTS.md`) |
| `hooks/` | Custom React hooks — SSE live events and toast state (see `hooks/AGENTS.md`) |
| `api/` | Backend client and React Query hooks (see `api/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- `App.tsx` is the composition root: new top-level panels are added here, wired to data via the `api/` hooks rather than fetching inline.
- The `Scenario`/`BgType`/`Orientation` unions in `types.ts` must stay in lockstep with backend `modules/validation.py` enums and the worker's scenario routing. Changing one side without the other breaks generation requests.
- UI state (selected chorus, open modal, toast) lives in `App.tsx` via `useState`; server state lives in React Query — don't duplicate server data into local state.

### Testing Requirements
- No unit tests; the gate is `npm run build` (runs `tsc -b`, so type mismatches fail). Verify visually with `npm run dev`.

### Common Patterns
- One component per file under `components/`; explicit prop interfaces; callbacks (`notify`, `onSelect`, `onOpen`) passed down from `App.tsx`.
- Server interaction exclusively through `api/queries.ts` hooks.

## Dependencies

### Internal
- `components/`, `hooks/`, and `api/` (siblings); shared shapes from `types.ts`.

### External
- React 18, `@tanstack/react-query`.

<!-- MANUAL: -->
