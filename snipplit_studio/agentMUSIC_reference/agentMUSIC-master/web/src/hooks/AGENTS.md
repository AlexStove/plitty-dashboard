<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-15 | Updated: 2026-06-15 -->

# hooks

## Purpose
Custom React hooks for cross-cutting UI behavior: a Server-Sent Events subscription that pushes live job/stats updates into the React Query cache, and a small toast-notification state hook.

## Key Files
| File | Description |
|------|-------------|
| `useSSE.ts` | `useLiveEvents(enabled)` — opens an `EventSource` to `/api/events`, parses `LiveEvent` messages, and writes `stats`/`jobs` straight into the React Query cache via `qc.setQueryData`. Auto-reconnects after 3s on error and cleans up on unmount. |
| `useToast.ts` | `useToast()` — manages transient toast state; returns `{ toast, notify, clearToast }` used as the `notify` callback threaded through components. |

## For AI Agents

### Working In This Directory
- `useLiveEvents` is the live-update mechanism: it pushes server state directly into query keys (`['stats']`, `['jobs']`), so those queries get fresh data without refetching. If you add a new live-updated key, update the message handler here to `setQueryData` for it (and keep the key name identical to the one in `api/queries.ts`).
- Preserve the EventSource lifecycle discipline: guard with a `closed` flag, clear the retry timer, and `es.close()` in the effect cleanup to avoid leaked connections on unmount/re-render.
- Toast display is decoupled: this hook holds state; the `Toast` component renders it. Pass `notify` down rather than rendering toasts inline.

### Testing Requirements
- No unit tests; type-checked by `tsc -b` during `npm run build`. Verify SSE behavior manually with `npm run dev` against a running backend.

### Common Patterns
- Hooks own side effects in `useEffect` with explicit cleanup; they integrate with React Query via `useQueryClient()` rather than holding their own copies of server data.

## Dependencies

### Internal
- `../types.ts` (`LiveEvent`); consumed by `../App.tsx` and components needing `notify`.

### External
- React; `@tanstack/react-query`; the browser `EventSource` API.

<!-- MANUAL: -->
