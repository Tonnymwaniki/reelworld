# Build log

One entry per phase: done, tested how, commit id, open problems.
On session restart, read this + `docs/build_plan.md` and continue at
the first unfinished phase.

## Phase 0 — foundation (done)

- Wrote `docs/build_plan.md` (41 screens → routes → endpoints, new vs
  existing), `docs/deferred.md`, this log; updated `AGENTS.md` (Reel,
  English-only, demo mode, phases).
- Tokens: merged design_system_v6 (authoritative) + papyrus set into the
  shell config and `frontend/styles.css`. Choices: `rounded-full` keeps
  9999px (screenshots show true pills; v6's `full: 0.75rem` contradicts
  them); radius DEFAULT/lg/xl adopted (old views will look tighter until
  their phase replaces them); `secondary` is now #476556 (v6), forest
  green stays under `forest`.
- Shell: export header (avatar removed: no user profiles; cluster pill
  is live API status, never a fake latency), 5-tab nav + mobile nav,
  demo banner + code field (sessionStorage only), export footer minus
  the GitHub link (no URL known; deferred), router with phase stubs,
  404 + error views from the export (fake node names, latencies, uptime
  and Inspect Pipe removed; real path/count/message/API check instead).
- Backend: `GET /api/config` (flags + real counts), demo gate
  (`X-Demo-Code`, 403) on upload, `GET /og-image.png`.
- `scripts/make_og_image.py` → `frontend/og-image.png` (1200×630, real
  photos/credits/counts 132/70/51; dropped fake latency, names, %s, domain).
- Old views stay live until replaced; unbuilt routes show honest stubs.
- Tested: `/api/config` (demo true, 132/16), `/` 200 (label/nav/og),
  `/views/404.html` 200, og 200 PNG, upload w/o code 403, gate branches
  (right code/no code/demo off), old endpoints OK, JS + both suites green.
- Commit id: (this commit; see `git log`).
- Open: footer GitHub link needs the real repo URL; Phase 1 builds Reel.
