# H3 workflow baseline

These API workflows derive from ComfyUI's native H3 templates, with reviewed
website parameters and reference connections.

| Mode | API template | Conditioning node | Checkpoint |
| --- | --- | --- | --- |
| Text to video | `h3_t2v_api.json` | `MiniMaxH3ImageToVideo` | fl2va |
| First/last frame | `h3_i2v_api.json` | `MiniMaxH3ImageToVideo` | fl2va |
| Multimodal references | `h3_r2v_api.json` | `MiniMaxH3ReferenceToVideo` | ref2va |

The baseline uses pruned INT8/convrot diffusion models, a Qwen3-VL 32B NVFP4/AWQ
encoder, FP16 video VAE and FP32 audio VAE. Sampler/scheduler are `res_multistep`
and `simple`, with a validated 20-step setting. Turbo/Lightning LoRA, FastH3 and
sparse/Sage attention patches are not part of this baseline.

The website supports 16:9, 9:16 and 1:1, using 360/576/720 tiers. Generation axes
align upward to 32 pixels, then center crop to the requested output. Requested
4-15 seconds align upward to `17k+5` frames at 24 fps. Requested 5 seconds gives
124 frames, about 5.167 seconds. The 4-second option is below the stated trained
range and was not part of real baseline GPU acceptance.

First/last mode requires a first image. Multimodal mode accepts up to 9 images,
3 video clips and 3 audio clips with validated purposes/numbering. The Worker
decodes/normalizes media and assembles reviewed native loading nodes. Browsers
cannot supply arbitrary node graphs or model paths.

Each API JSON has a matching mapping JSON. Review both together with Worker
`mapping.py` and the server schema/asset validators when upgrading. A node only
affects generation if connected to the executed sampler.

Preserve durable prompt recovery, exact output validation, full media decoding,
posters, HTTP Range and downloads when changing generation or exports.

The additive Director package is documented in
[the workflow handoff](../WORKFLOWS-DIRECTOR-HANDOFF.md), with the real versioned
registry at `workflows/h3_capabilities.json`. Native remains the default. The
Director package's GPU acceptance is distinct from application integration and
production activation; do not enable it from file presence alone.

References: [official guide](https://docs.comfy.org/tutorials/video/minimax/minimax-h3),
[templates](https://github.com/Comfy-Org/workflow_templates),
[models](https://huggingface.co/Comfy-Org/MiniMax-H3).
