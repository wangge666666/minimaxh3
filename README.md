# ComfyUI Cloud Hub

A private video studio using Next.js, a SQLite queue, an independent Python
Worker and native MiniMax H3 in local ComfyUI. The validated source baseline is
**[v1.0.0](BASELINE-v1.0.md)**.

开发接手先读：[项目进度与运行逻辑](PROJECT-OVERVIEW.md)，再读
[导演台并行分工](COLLABORATION-DIRECTOR.md)。说明中区分生产基线、应用候选与工作流草稿。

Browser -> private HTTPS website -> SQLite queue -> Worker -> local H3 -> MP4.
It supports text-to-video, first/last frames, image/video/audio references,
upload progress/recovery, persistent history, posters, playback and downloads.
The queue holds 500 unfinished jobs with one executing job. Mac image generation
is disabled in this deployment; historical image results remain usable.

This is a personal private-network application, not a completed public
multi-user SaaS service. Keep Node on loopback and use a private HTTPS origin.

## Source and environment

- `apps/web`: website, validated API and SQLite queue.
- `apps/worker`: Worker, reviewed graph construction, media decoding and recovery.
- `workflows`: API JSON and field mappings.
- `scripts/windows`: independent scheduled-task controls and update helpers.
- `docs/baselines/v1.0.0.json`: workflow hashes and runtime/model identities.

Use Node.js 24+, pnpm 11.25.0 and an independent Python 3.12 environment. Do not
install dependencies into ComfyUI's environment.

```powershell
pnpm install --frozen-lockfile
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -X utf8 -m pip install -r apps/worker/requirements-dev.lock
.\.venv\Scripts\python.exe -X utf8 -m pip install --no-deps -e apps/worker
.\.venv\Scripts\python.exe -X utf8 scripts/setup-private-studio.py --origin https://your-device.your-tailnet.ts.net:8443
```

Configure `apps/worker/.env` with `H3_COMFYUI_BASE_URL=http://127.0.0.1:8189`,
local cloud API `http://127.0.0.1:3000`, concurrency 1 and a separate Worker state
directory. Set `IMAGE_GENERATION_ENABLED=0` for the Worker and
`MVP_IMAGE_GENERATION_ENABLED=0` in `apps/web/.env.local`. Keep machine tokens
private. `.env.example` lists configuration fields.

Run `pnpm test`, `pnpm typecheck`, Worker tests and `pnpm build`. Windows Python
subprocess tests require `$env:PYTHONUTF8='1'`. Start the website from `apps/web`
and the Worker from `apps/worker` so relative database/workflow paths are correct.

Windows service controls:

```powershell
.\scripts\windows\hub.ps1 install
.\scripts\windows\hub.ps1 start
.\scripts\windows\hub.ps1 status
.\scripts\windows\hub.ps1 logs
.\scripts\windows\hub.ps1 stop
```

The existing script uses deployment-specific task names and starts after the
configured Windows user signs in. Review it before using another machine.
ComfyUI remains separately managed. Normal stop refuses unfinished jobs.

## Upgrades and private data

Read [baseline/recovery instructions](BASELINE-v1.0.md),
[workflow details](docs/workflow-baseline.md) and [agent rules](AGENTS.md). Work on
a new `codex/<change-name>` branch in a separate worktree and preserve the baseline
tag. Enable local safeguards with `git config core.hooksPath .githooks`.

Credentials, private handoff reports, databases, migration snapshots, media,
Worker state, logs, environments and build output are excluded from this public
repository. Git restores source, not private data or external model/runtime files.
