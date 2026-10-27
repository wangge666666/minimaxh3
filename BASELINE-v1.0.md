# Validated baseline 1.0

This captures the working source and H3 workflows validated on 2026-10-28
(Asia/Taipei). The immutable annotated tag is **`v1.0.0`**, with a baseline branch
`codex/baseline-v1.0`. Repository version 1.0 is independent of upstream ComfyUI
and individual component package versions.

The baseline has a Next.js website, SQLite queue and one Python Worker on
Windows. H3 runs locally at `http://127.0.0.1:8189`. It supports text-to-video,
first/last frames and image/video/audio references, with 500 unfinished jobs.
Mac image generation is disabled, while historical image results remain usable.

## Versioned scope

Git contains source, reviewed API graphs/mappings, dependency locks, general
service scripts, tests and sanitized documentation. The machine-readable record
`docs/baselines/v1.0.0.json` pins workflow hashes, runtime versions and checkpoint
identities. Model SHA256 values are from an earlier verified local manifest;
this baseline does not claim to have rehashed all model weights today.

Credentials, private reports, SQLite/WAL files, migration snapshots, uploaded
references, generated results, Worker journals, environments and build output
remain local and ignored. The GitHub repository is public: do not force-add them.

## Start an upgrade

Create an isolated branch/worktree instead of editing the live directory:

```powershell
git worktree add -b codex/workflow-upgrade D:\AI\ComfyUI-Cloud-Hub-workflow-upgrade v1.0.0
git config core.hooksPath .githooks
```

Enable hooks in a new clone with `git config core.hooksPath .githooks`. Give the
test checkout its own environment, database, Worker state and port. Never copy
the production submission journal or connect a test Worker to production.

Check the starting workflow hashes with `scripts/windows/check-baseline.py`.
Review intended edits with:

```powershell
git diff v1.0.0 -- workflows apps/worker/src apps/web/src
```

Run relevant checks in the isolated checkout:

```powershell
pnpm test
pnpm typecheck
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -X utf8 -m pytest apps/worker/tests -q
.\.venv\Scripts\python.exe -X utf8 -m ruff check apps/worker
pnpm build
```

Start real GPU acceptance at 640x360, requested 5 seconds, 20 steps and one
reference image. Compare the same seed/settings before testing larger jobs.
Check actual frames, dimensions, sound, full decode, poster, Range and download.
The baseline's three 1280x720 / 5-second / 20-step jobs completed with processing
times of about 6m45s, 7m24s and 8m03s. Other settings need separate measurements.

## Recover source

```powershell
git worktree add --detach D:\AI\ComfyUI-Cloud-Hub-v1.0-recovery v1.0.0
```

This creates clean recovery source without switching production. Before an
actual rollback, finish active jobs, back up SQLite consistently and preserve
private configuration. Restore reviewed source/build with the existing data,
then restart only the Hub. Do not replace the database with an older snapshot.
Git cannot restore external ComfyUI, models, Torch or environments.

Do not run routine `git reset --hard` or `git clean` in the live directory. Keep
`v1.0.0` fixed and record upgrades with new commits and new version tags.
