# Baseline and safe workflow upgrades

The validated starting point is annotated tag `v1.0.0`. Read `BASELINE-v1.0.md`
and `docs/workflow-baseline.md` before changing generation behavior.

- Never move, replace, amend or delete `v1.0.0` or rewrite its history.
- Upgrade on a new `codex/<change-name>` branch in a separate worktree. Keep the
  live checkout, private configuration, production database and Worker journal
  intact. Never start a test Worker against the production queue.
- API JSON, mappings, Worker graph construction and server validation form one
  contract; review them together. Do not accept arbitrary browser graphs/paths.
- Preserve ComfyUI 8188/8189, models, shared input/output and startup scripts.
  Do not update Torch, replace weights or upgrade ComfyUI incidentally.
- H3 uses `http://127.0.0.1:8189`. Preserve `--disable-pinned-memory` and dynamic
  VRAM. Do not add `--disable-dynamic-vram` without a separately justified change.
- Preserve Tailscale 443; Hub uses private HTTPS 8443 and loopback website 3000.
  Do not enable Funnel or expose the local queue publicly.
- Mac image generation is disabled. Preserve historical image playback and H3
  image/video/audio references. Queue capacity is 500 with concurrency 1; state
  must return all active jobs so the Worker can recover an older prompt.
- Never commit credentials, private DBs, snapshots, media, runtime/build output,
  Worker journals or machine-specific handoff reports. Check staged files and
  scan live credentials before publishing, including in a public repository.
- Use isolated databases for tests. Run appropriate TypeScript/Worker checks;
  Windows Python subprocess tests require `PYTHONUTF8=1`. Read web AGENTS.md
  before web edits. Never fill production with fake capacity-test jobs.
- Compare fixed seed/settings with baseline. Start GPU checks at 640x360,
  requested 5 seconds, 20 steps and one reference image. Check frames, sound,
  dimensions, full decode, poster, playback, Range and download. Validate larger
  or accelerated configurations separately; do not claim unmeasured speedups.
- Before rollout, back up SQLite consistently and save private configuration.
  Never interrupt an active ComfyUI prompt for a code deployment; preserve
  queued IDs and durable submission recovery, without uncertain resubmission.
- Git rollback restores source only, not DBs, models, ComfyUI or environments.

Optional local safeguards: `git config core.hooksPath .githooks`.
