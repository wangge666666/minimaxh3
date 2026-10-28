# Director application and workflow integration

This source integration combines workflow candidate
`7d106504473b12379ac14bb98942c0c44efff530` and application candidate
`b640d4a0effa0c052a80abc339585c0fb2d3f9d7`. The immutable `v1.0.0` baseline
and all eleven baseline workflow files remain unchanged. Source integration
does not switch the deployed Hub or enable Director on its ComfyUI instance.

## Dispatch contract

The default engine is `native`, including old jobs without engine metadata.
Director uses the existing modes `h3_t2v`, `h3_i2v` and `h3_r2v`, revision
`director-v1.0.0` and persisted output node IDs `["8"]`. The API chooses and
persists revision/output metadata; browser requests cannot choose graphs,
paths or that metadata. An unavailable revision fails instead of falling back
or submitting with a different template. The existing three-argument
`load_workflow(directory, mode, values)` interface remains compatible.

The accepted registry is `workflows/h3_capabilities.json`; API/mapping/editable
files and reference numbering are documented in
[WORKFLOWS-DIRECTOR-HANDOFF.md](WORKFLOWS-DIRECTOR-HANDOFF.md). The original
application candidate is described in
[DIRECTOR-APP-HANDOFF.md](DIRECTOR-APP-HANDOFF.md). Its statement that Director
is unavailable describes that earlier candidate, before this integration.

Director is opt-in on both sides:

- Web: `MVP_DIRECTOR_ENABLED=1`, with
  `MVP_DIRECTOR_COMFYUI_BASE_URL` set to the reviewed ComfyUI endpoint.
- Worker: `DIRECTOR_ENABLED=1`, with `H3_COMFYUI_BASE_URL` pointing at the same
  reviewed service and its workflow directory pointing at this package.
- `MVP_DIRECTOR_BUILDER_DIRECTORY` can explicitly locate the matching Worker
  source directory. The default is `../worker/src/comfy_hub_worker` relative
  to the web working directory. Standalone packaging traces those three
  builder files along with the registry and acceptance evidence.

The Web verifies fixed API/mapping hashes, the three sealed builder hashes,
per-mode GPU acceptance records and a bounded runtime `object_info` probe.
It checks node ports and actual model choices. Only an explicitly configured
loopback or private Tailscale HTTPS endpoint is accepted. The observation has
a five-second lifetime and a three-second request timeout. Missing files,
unsupported ports/models or an offline service make Director unavailable.
A rejected Director request returns 503 before creating a job. Native jobs
retain their existing queue behavior. Worker also validates the enabled flag,
persisted revision/output and complete reference descriptors before submitting.

Image/video/audio references remain limited to 9/3/3, with contiguous numbering.
Video soundtracks participate only when the existing option enables them.
FL2VA serves text and first/last frames; REF2VA serves reference generation.
The default remains 20 steps, with no automatic accelerated model switch.
H.264/AAC MP4 output passes the existing crop, poster, faststart, playback,
Range and download path. Known-prompt recovery uses the saved prompt/output
snapshot and does not rebuild or resubmit a graph after a restart.

## Executed acceptance

Sanitized machine-readable integration evidence is in
`workflows/validation/director-integration-v1.json`. Original per-mode GPU
evidence remains in `workflows/validation/director-v1.0.0.json`.

- TypeScript tests: 80 passed. Worker Python tests: 254 passed. Type checking,
  Ruff and production build passed; all eleven baseline files matched.
- Four integrated GPU jobs completed through HTTP, SQLite, Worker, ComfyUI and
  postprocessing: Director text, first/last frames, combined image/video/audio,
  and a native request omitting engine metadata. Each submitted exactly once.
  Each requested five seconds at 640x360 and 20 steps, producing 124 frames
  at 24 fps, H.264/AAC, fully decodable output and a JPEG poster. HEAD, prefix
  and suffix Range, ETag 304 and byte-identical downloads passed.
- Worker restart during an accepted GPU prompt recovered the same prompt.
  Web/Worker restart preserved seven completed jobs; a second Worker using
  the same state directory was rejected. Queue capacity remains 500 and
  concurrency one.
- Local Windows Chrome played a completed clip to its end without an error;
  an actual browser download matched the output bytes. Three additional
  private story samples exercised all three Director modes. Their Chinese
  dialogue word accuracy and lip synchronization have not been accepted.
- With only the isolated ComfyUI stopped, Director returned 503 without
  inserting a job. A native request still queued and was canceled before claim.
- A consistent read-only copy of the existing database was served separately,
  without a Worker: 25 historical jobs remained logically unchanged; all 16
  completed media files and their posters were readable and byte-verified.

All integration services used separate ports, configuration, database, inputs,
outputs and Worker state. Private prompts, media, credentials, logs, database
copies and journals are excluded from the repository. Production services,
models, Torch, network routes and the production database were not changed.

## Remaining validation and rollout boundary

The physical M64 browser and production scheduled-task restart/boot have not
been exercised. Larger resolutions, every duration/ratio, the maximum 15
references and accelerated variants need separate GPU acceptance. Editable
graphs passed structural tests, but manual frontend import/export was not
accepted: the isolated browser navigation received HTTP 403; origin protection
was not weakened. Exact generated dialogue and lip synchronization require
listening and visual review. These limits do not imply production rollout.

Before a later rollout, finish active GPU work, use the consistent SQLite
backup tooling, preserve private configuration/journal and minimally load the
audited Director plugin. Do not enable every custom node. Old source may not
understand newly persisted Director jobs; source rollback must retain the
current database and account for unfinished jobs. Never restore an old database
over new records, move `v1.0.0`, or treat Git rollback as environment recovery.
