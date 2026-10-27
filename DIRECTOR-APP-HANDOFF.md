# Director application candidate

Application branch: `codex/director-app`. Common starting commit:
`533c8d80134db4edd7b8d71649c14113fc541c2d`. Baseline tag `v1.0.0` is unchanged.

This candidate implements the application work in collaboration section 5.
Director generation remains unavailable until the workflow owner delivers an
accepted registry, loader and GPU evidence. The existence of a registry file
does not enable generation. No registry JSON format has been invented here.

## Application changes

- All three existing H3 modes have native/director selection and explicit
  readiness. Selecting another engine preserves parameters and selected files.
  Unready selection disables submission. History displays the generation method.
- Browser creation accepts optional `workflowEngine: native | director` and
  rejects unknown engines, revisions, output node IDs, graphs and paths. Missing
  engine means native. Director requests currently return HTTP 503.
- The server pins native `workflowRevision` and `workflowOutputNodeIds`, plus
  defaults for frames/fps/steps/sound/reference options, before inserting a new
  job. These travel through history, request-ID lookup, claim and completion.
  A retry returns the original job, even after a template/configuration change.
- Metadata uses the existing `jobs.params` JSON. There is **no new SQL schema
  migration**, history rewrite, or retroactive revision assignment. Old records
  and journals without engine/revision remain native and recoverable.
- `workflow-options.ts` is the browser-safe normalized option model;
  `workflows.ts` is the server adapter awaiting the real registry contract.
  Native options and existing schema use the same `h3.ts` limits. The Worker
  checks the immutable task against local files before building/submitting.
- `workflow_dispatch.py` only validates application metadata and descriptors.
  Graph construction still calls the existing `load_workflow(directory, mode,
  values)`. `workflowEngine` and `workflowRevision` are passed in `values` along
  with the existing parameters and normalized assets (`key`, `kind`, `path`,
  `has_audio`). Director dispatch is deliberately blocked before graph loading.
- Recovery resolves a pending submission before building anything. A known
  prompt uses its persisted output IDs, without rechecking today's capabilities
  or rebuilding a graph. A legacy native journal can recover output IDs from its
  mapping. Cloud/journal prompt and metadata conflicts fail without submission.
  Startup prioritizes the journal even when current templates are missing.
- `MVP_DATABASE_PATH`, `MVP_LOCAL_PORT`, and `MVP_WORKFLOW_DIRECTORY` allow an
  independent checkout/database/port. Defaults preserve the existing deployment.
  Only explicitly configured loopback origins are added for the development port.
- Next server tracing includes workflow source assets and excludes local state
  and private environment files. Custom workflow directories must be provisioned
  separately; they are server configuration, never browser input.
- `scripts/prepare-director-app.py` inspects an explicit database read-only and
  can create a consistent SQLite backup without overwriting an existing file.
  It reports counts only, changes no queue state, and exits 2 while jobs are
  claimed/running/uploading. It never controls services or connects to ComfyUI.

## Native revision protocol

For a mode, hash its fixed `<stem>_api.json`, then `<stem>_mapping.json`, using
SHA256 over concatenated UTF-8 strings `filename + NUL + contents + NUL`.
Normalize CRLF to LF before hashing. Prefix the digest with `native-sha256:`.
For images, `<stem>` is `z_image_turbo_text` or `z_image_turbo_img2img`.
For H3 it is the existing mode identifier. No browser-supplied filename is used.
Web and Worker use the same protocol; HTTP smoke tests compare their results.

The digest pins the graph and mapping files. It does not hash models or claim
that a changed Python graph builder is equivalent. Keep the reviewed builder
commit installed with the corresponding templates. The Director handoff must
also identify the builder/registry revision explicitly.

## Preserved behavior and validation

| Existing behavior | Application evidence |
| --- | --- |
| Native text, first/last, multimodal; old request formats | Schema/API tests; native loader unchanged |
| 9 images / 3 videos / 3 audio, continuous numbering and purposes | Existing upload tests; Worker descriptor tests and real synthetic-media normalization/forwarding |
| Video audio references, sound on/off, reference image sizing | Existing media tests; image/video/audio forwarding test; muted and sound exports |
| Three ratios, 360/576/720, 4–15 seconds, seed, 12/20/30 steps | Existing H3/schema/export tests; defaults remain 20 steps |
| 24fps, 17k+5 frames, aligned canvas and crop | Existing H3/mapping/video tests remain intact |
| Required native first frame, optional last frame | Existing validation unchanged; no tail-only extension |
| Capacity 500, concurrency 1, every unfinished job visible | Existing isolated queue boundary and old-prompt tests |
| Upload progress/retry, history, cancel/reuse, posters, Range/download | Existing client/media/API tests and isolated production-build browser smoke |
| Journal, prompt identity, lease and single instance | Existing tests plus lost-response, version-change, missing-template, upload-resume and lock tests |
| Mac generation disabled; historical images usable | Existing feature-gating/playback tests; isolated website uses disabled image generation |
| Historical DB/media/private state | Consistent old DB copy opened twice; records/leases/prompt IDs/assets/results/posters unchanged; backup tests |
| Production services, model/runtime and network configuration | No production access or service operation; protected files unchanged |

Final checks were run on an independent macOS checkout using Node **24.22.1**,
pnpm **11.25.0**, and a new Python **3.12.14** `.venv`, installing the existing
locks without changing them. Initial baseline: TypeScript **68**, Python **109**.

Final application checks:

- `pnpm test`: **75 passed** (2 shared + 73 web).
- `pnpm typecheck`: passed for shared and web.
- `PYTHONUTF8=1 .venv/bin/python -m pytest apps/worker/tests -q`: **133 passed**.
- `.venv/bin/python -m ruff check apps/worker scripts/prepare-director-app.py`:
  passed.
- `pnpm build`: passed, with no build warnings.
- `scripts/windows/check-baseline.py`: all **11** protected workflow files
  unchanged. Scope audit also excludes `mapping.py`, `director_*.py`, workflow
  tests and ComfyUI configuration.
- Built website on loopback **3100**, separate `.runtime/app-smoke.sqlite`, no
  Worker connected. Browser verified all three Director modes remain unready,
  prompt/duration/uploaded-image preservation across engine switches, native
  upload/queue/history and cancellation.
- HTTP smoke compared web/Worker native revisions for all three modes, retried
  request IDs, refused unready Director generation and inspected/consistently
  backed up the isolated database. Test state never entered production.
- Build trace checked for workflow assets and absence of `.env`, `.local-data`,
  `.runtime` and `.venv` files.

## Interface questions for the workflow owner

1. Deliver the exact accepted commit, real `h3_capabilities.json` sample/schema,
   its version and explicit acceptance state for each engine/mode. Specify
   immutable revision lookup, defaults, parameter/media limits and behavior when
   a pinned revision is no longer installed. File presence is insufficient.
2. Confirm how the compatible `load_workflow(directory, mode, values)` dispatches
   `workflowEngine`/`workflowRevision`, and which helper validates/resolves them.
   Keep native absence semantics and `output_node_ids: list[str]` compatible.
3. Specify stable output IDs, accepted MP4 output metadata, and how to retain old
   revision assets for queued jobs. The application snapshots output IDs for
   prompt recovery; it must not switch queued work to a new template.
4. Confirm all normalized reference descriptors reach the correct sampling path,
   including video audio and `refImageSize`, and provide the actual limitations.
   If any combination is unsupported, expose a validation error before enqueue
   or submission; do not discard a reference.
5. Supply separate T2V/I2V/R2V GPU evidence from 640×360, requested 5 seconds,
   124 frames, 20 steps. Provide full decode/MP4/audio/frame/dimension evidence,
   output IDs, error samples, and the minimum 8189 node requirements.

Once delivered, update the single server registry adapter, the Worker dispatch
guard and stored revision validation to the **actual** contract. Do not merely
remove the Director guard. No messages were sent to another chat; this document
is intended for the user to hand over.

## Deployment preparation and outstanding acceptance

This branch is a candidate for integration, not a G58 production deployment.
Do not run `hub.ps1 install/start/stop` from a test checkout. Existing service
scripts still target production task names and were not modified.

On the integration machine, install the two explicitly reviewed source commits
and existing locks in an independent environment. Configure separate loopback
port (for example 3100), database path, Worker ID/token and state directory;
point synthetic tests only at their isolated API. Do not copy a live journal or
production token into the test environment. ComfyUI, Torch and model installation
remain the workflow owner's responsibility.

Before any production change, the workflow owner should wait for active prompts
to finish naturally, preserve queued IDs and private configuration/journal, and
use SQLite's backup API for a consistent snapshot. The helper can be run against
an explicitly chosen database, using a new private snapshot path:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/prepare-director-app.py --database <explicit-db> --backup <new-private-snapshot.sqlite>
```

Exit 2 means executing tasks remain; a backup is not permission to stop them.
Recheck the queue immediately before a coordinated service change. Keep all
snapshots, media and configuration outside Git. This change needs no SQL DDL.
**Source rollback to v1.0.0 alone is insufficient:** its strict completion schema
does not understand new persisted metadata. Use a compatible application build;
never restore an older DB over jobs created during the upgrade.

Outstanding: actual Director registry/loader integration, three-mode real GPU
generation and quality/performance acceptance, G58/Windows service lifecycle,
M64 browser playback/Range/download with real generated audio/video, and survival
after closing terminals/Codex. Four-second generation remains supported but has
no new GPU quality claim. No acceleration or multi-shot feature is advertised.

No changes were made to workflows, mapping, Director graph helpers, corresponding
workflow tests, models/Torch, ComfyUI startup/configuration, network configuration,
baseline refs or production data/services. Rollout remains with the workflow owner.
