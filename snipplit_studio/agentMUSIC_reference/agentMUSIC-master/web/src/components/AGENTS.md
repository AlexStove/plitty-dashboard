<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-15 | Updated: 2026-06-15 -->

# components

## Purpose
The dashboard's UI components — both feature panels (track sources, generation, chorus list, job monitor, video gallery) and chrome (header, vinyl spinner, toast). Each is a function component in its own file, composed by `../App.tsx` and fed data via the `../api/` hooks.

## Key Files
| File | Description |
|------|-------------|
| `Header.tsx` | Top bar; shows a `loading` indicator. |
| `VinylDisc.tsx` | Animated vinyl that spins while jobs are active; displays `stats` and active-job count. |
| `SourceTabs.tsx` | Tab switcher across the three import sources; hosts the tab panels below. |
| `UploadTab.tsx` | Direct audio file upload. |
| `SpotifyTab.tsx` | Spotify URL import (`useSpotifyImport`). |
| `MinioTab.tsx` | Browse/select MinIO tracks and batch-import (`useMinioTracks`, `useMinioImport`). |
| `GeneratePanel.tsx` | Scenario / background / orientation / count selection; launches generation (`useGenerate`) for the selected chorus. |
| `ChorusesPanel.tsx` | Lists choruses; controlled selection via `selected` / `onSelect`. |
| `JobsPanel.tsx` | Active/recent job list with progress; stop action (`useStopJob`). |
| `VideosGrid.tsx` | Gallery of rendered videos; opens a video via `onOpen`. |
| `VideoModal.tsx` | Detail/playback modal for a selected `Video`. |
| `Toast.tsx` | Renders a transient toast and calls `onDone` when finished. |

## For AI Agents

### Working In This Directory
- One component per file; export a named function component with an explicit props interface defined just above it.
- Components are presentational + action-dispatching: read server data from props (passed down from `App.tsx`) and trigger changes through `../api/` mutation hooks. Avoid calling `fetch` directly here.
- Cross-cutting feedback uses the `notify` callback (from `useToast`) threaded down as a prop — use it for success/error messages instead of ad-hoc UI.
- Selection-style state (e.g. selected chorus, open video) is lifted to `App.tsx` and passed back via `selected`/`onSelect`/`onOpen` props; keep these controlled rather than holding duplicate local copies.

### Testing Requirements
- No unit tests; type-checked by `tsc -b` during `npm run build`. Verify visually with `npm run dev`.

### Common Patterns
- Props interface above the component; callbacks (`notify`, `onSelect`, `onOpen`, `onClose`, `onDone`) for parent communication; styling via global classes in `../styles.css`.

## Dependencies

### Internal
- `../api/queries.ts` (data + mutation hooks), `../hooks/` (`notify` from `useToast`), `../types.ts` (`Job`, `Chorus`, `Video`, `Stats`, etc.), composed by `../App.tsx`.

### External
- React; `@tanstack/react-query` (via the hooks).

<!-- MANUAL: -->
