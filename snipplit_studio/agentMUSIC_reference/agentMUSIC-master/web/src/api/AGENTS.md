<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-15 | Updated: 2026-06-15 -->

# api

## Purpose
The dashboard's data layer: a low-level fetch wrapper plus a set of TanStack React Query hooks that read backend state (stats, jobs, choruses, videos, MinIO tracks) and perform mutations (generate, stop job, Spotify/MinIO import). All backend communication for the UI goes through here.

## Key Files
| File | Description |
|------|-------------|
| `client.ts` | Fetch wrapper with timeout + error handling. Exposes `api<T>(path)` (GET-style typed fetch) and `jsonPost<T>(path, body, timeoutMs?)` for JSON mutations. |
| `queries.ts` | React Query hooks built on `client.ts`: queries `useStats`, `useJobs`, `useChoruses`, `useVideos`, `useMinioTracks`; mutations `useGenerate`, `useStopJob`, `useSpotifyImport`, `useMinioImport`; plus the `refetchAll(qc)` helper and an `extract<T>` response normalizer. |

## For AI Agents

### Working In This Directory
- Components must not call `fetch` directly — add or reuse a hook here. This keeps query keys, polling intervals, and cache invalidation centralized.
- Query keys are simple string arrays (`['stats']`, `['jobs']`, `['choruses']`, `['videos']`, `['minio']`); mutations invalidate the relevant keys in `onSuccess`. Reuse the same key when adding a hook that touches existing data.
- Backends return either a bare array or `{ <key>: [...] }`; the `extract<T>(v, key)` helper normalizes both — use it for new list endpoints rather than assuming a shape.
- Mutations set explicit timeouts for slow operations (generate 60s, Spotify import 120s, MinIO batch import 300s). Match the timeout to the backend operation's real duration.
- Polling intervals: stats/jobs every 8s, choruses/videos every 15s, all with `refetchIntervalInBackground: false`. Live job/stats updates are pushed via SSE (`hooks/useSSE.ts`), so polling is a fallback — keep intervals conservative.

### Testing Requirements
- No unit tests; correctness is enforced by `tsc -b` during `npm run build`. The hook return types are tied to interfaces in `../types.ts`.

### Common Patterns
- One exported hook per query/mutation; `useQueryClient()` for invalidation; typed generics threaded from `../types.ts`.

## Dependencies

### Internal
- `../types.ts` (`Stats`, `Job`, `Chorus`, `Video`, `MinioTrack`, `GenerateParams`); consumed by `../App.tsx` and `../components/`.

### External
- `@tanstack/react-query`; the browser `fetch` API.

<!-- MANUAL: -->
