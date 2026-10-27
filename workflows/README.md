# Reviewed API workflows

The video baseline uses three native H3 API templates and matching mappings:

- `h3_t2v_api.json`: text-to-video using fl2va.
- `h3_i2v_api.json`: first/last-frame video using fl2va.
- `h3_r2v_api.json`: multimodal references using ref2va.

Each has a matching `*_mapping.json`. The original API export hashes are in
`h3-provenance.json`. The Hub changes the output prefix and supplies reviewed
parameters/reference connections. See [baseline details](../docs/workflow-baseline.md).

Worker `load_workflow` validates supported modes, paths, node/input mappings,
types, limits and output nodes. Browser callers cannot supply graphs or model
paths. Preserve prompt recovery and output validation when upgrading.

Legacy Z-Image API/mapping files remain for compatibility. New Mac image
generation is disabled in the baseline deployment.
