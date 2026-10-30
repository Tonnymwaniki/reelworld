# Deferred: designed but not backed by data or a key

Items the exports imply that are NOT built. The UI must not show them
(except behind an off feature flag where noted). Revisit only with the
missing input in hand.

| Item | Why deferred | UI treatment |
|---|---|---|
| SAM 3.1 outlines | implemented in `POST /api/outline` (boxes + opaque masks); awaiting first live verification | `FEATURE_OUTLINES=true`; mask raster decode later (alphabet unverified) |
| Voice input (mic in chat bar) | no speech backend; rule 9 | behind the same off flag; no fake waveform |
| Likes, comments, ranking, share counts | no social backend; brief forbids them on Showcase | removed wherever the exports show them |
| Maps, GPS pins, user profiles, notifications, settings | no such features | removed wherever the exports show them |
| MP4 export | browsers record WebM; brief says do not promise MP4 | WebM only, labelled honestly |
| Swahili UI | English-only product rule | no Swahili code remains; `ENABLE_SWAHILI` reserved |
| Thread tune/lens panel | export shows the button but no panel | button hidden until designed (P1) |
| Publish personal→world from thread | no such endpoint | button removed from the add-photo reply (P1) |

More rows are added per phase as screens are wired (rule 2).
