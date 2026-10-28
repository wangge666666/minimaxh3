# Director 工作流交付契约 v1

工作流分支 `codex/director-workflows`；协作起点 `533c8d80134db4edd7b8d71649c14113fc541c2d`。
应用候选 `b640d4a0effa0c052a80abc339585c0fb2d3f9d7` 已核对，本分支没有改写应用负责人文件。
安装时以本交付的完整 Git SHA 固定整包；不要只复制一个 JSON，也不要切换生产 Hub。

## 文件与调用

| mode | Director API | mapping | 可编辑图 |
| --- | --- | --- | --- |
| `h3_t2v` | `workflows/h3_director_t2v_api.json` | `workflows/h3_director_t2v_mapping.json` | `workflows/h3_director_t2v_editable.json` |
| `h3_i2v` | `workflows/h3_director_i2v_api.json` | `workflows/h3_director_i2v_mapping.json` | `workflows/h3_director_i2v_editable.json` |
| `h3_r2v` | `workflows/h3_director_r2v_api.json` | `workflows/h3_director_r2v_mapping.json` | `workflows/h3_director_r2v_editable.json` |

原有 API/mapping 全部保留，11 个基线文件的 SHA256 不变。
`load_workflow(directory: Path, mode: str, values: dict) -> (dict, list[str])` 边界不变。
`mapping.py` 负责分派；`director_workflow.py` 负责单条 Director Group、素材连接及固定画布；
`director_contract.py` 提供 `director_metadata(directory, mode)` 和 `native_workflow_revision(directory, mode)`。
`director_runtime.py` 仅核对插件及复制至一个不存在的新目录，不安装依赖、不启动服务、不覆盖插件。

```python
revision, outputs = director_metadata(workflow_directory, "h3_r2v")
# 由服务端固定并持久化；浏览器不能指定 revision、输出 ID、图、模型或路径。
values = {
    "workflowEngine": "director", "workflowRevision": revision,
    "workflowOutputNodeIds": outputs,
    "prompt": "The boat in <Picture 1> moves as in <Video 1>. Use <Audio 2>.",
    "seed": 42, "width": 640, "height": 360,
    "durationSeconds": 5, "frames": 124, "fps": 24, "steps": 20,
    "sound": True, "referenceVideoAudio": True, "refImageSize": "match",
    "assets": [
        {"key": "ref_image_0", "kind": "image", "path": "hub/validated.png"},
        {"key": "ref_video_0", "kind": "video", "path": "hub/validated.mp4", "has_audio": True},
        {"key": "ref_audio_0", "kind": "audio", "path": "hub/validated.wav"},
    ],
}
graph, output_node_ids = load_workflow(workflow_directory, "h3_r2v", values)
```

路径来自现有 Worker 上传响应，只接受相对 input 路径，不接受 URL、盘符、回退路径或 `[output]` 标注。
应用的素材下载、解码、规范化、上传、用途校验和 journal 仍由应用负责人维护。

## engine、revision 与恢复

- 缺少 `workflowEngine` 的旧请求、旧任务仍为 `native`。未知 engine 报 `WorkflowError`，不降级。
- Native 新任务使用应用候选既有 `native-sha256:<digest>` 协议：依次对固定 API、mapping 的
  `filename + NUL + canonical-LF-content + NUL` 求 SHA256。五个原生模式均已与应用代码逐项比对。
  旧任务缺 revision 仍可构图；显式 revision 不匹配拒绝。能力表缺失不影响旧原生入口。
- Director 本版 revision 固定为 **`director-v1.0.0`**。缺失、未知、未安装的修订拒绝；不自动选择新版本。
  API、mapping 和三个构图模块都有 canonical-LF SHA256，`director_metadata` 核验它们后才返回 `("director-v1.0.0", ["8"])`。
- 服务端入队时持久化 engine、revision、参数、素材和 `workflowOutputNodeIds`。
  应用侧 `workflow_dispatch.py` 应用本契约替换现有 Director 阻断：核验固定修订/输出、校验素材，再调用 loader。
  不应仅移除 guard。网页服务端适配器位于 `apps/web/src/lib/mvp/workflows.ts`，由应用负责人修改。
- 已有 prompt 优先使用原 prompt 与持久化输出恢复，不调用新模板重建后重新提交。
  原模板不再安装且任务尚未提交时，应明确失败并等待恢复该版本；本版不提供自动历史版本替换。
  发布新修订时保留旧完整 release 目录，由应用的版本路由指向对应已审查目录。
- Native 输出仍为 `92`，Director 唯一媒体输出为 **`8` (`SaveVideo`)**。
  `workflowOutputNodeIds` 如有提供，必须与该引擎和修订一致。

## 能力表与就绪状态

真实能力表为 `workflows/h3_capabilities.json`，`schemaVersion: 1`；格式见同目录 schema。
`defaultEngine` 为 `native`。每个 `engines[engine].modes[mode]` 提供 `available`、`revision`、
`template`、`mapping`、`fileSha256`、`outputNodeIds`、`outputKind`、模型家族与 `validation`。

`available` 表示该固定工作流包完成所列验收，不代表目标机器已经部署。
Director 的 `activation.defaultEnabled` 为 false：实际 `ready` 还必须满足应用适配完成、明确启用、
目标 ComfyUI 节点/模型探测通过。仅发现文件不可启用；生产 8189 尚未加载 Director。
`validation.profiles` 和公开脱敏证据明确列出实测范围；支持参数不等于所有组合都做过 GPU 验收。

应用可直接映射：`defaults.steps/durationSeconds` 到现有选项 defaults，
`parameters.durationSeconds.min/max`、`steps`、`ratios`、`resolutions` 到现有 limits。
服务端与 Worker 使用相同来源；不在客户端接受任意 workflow graph/path/model。

## 参数、素材与音频

- 仍支持 16:9、9:16、1:1，360/576/720 档，历史 640×384；具体输出尺寸对见 `parameters.dimensions`。
  生成画布向上对齐 32，再交给现有 `finalize_video` 中心裁剪。
- 请求 4–15 秒；24fps；`5 + 17 * ceil((ceil(seconds*24 - 1e-9)-5)/17)` 帧。
  5 秒为 124 帧，约 5.167 秒。Group 收到的是已对齐的 `frames/fps`，避免 Director 的 round 与 Hub 的 ceil 差异。
- seed 0–4294967295；12/20/30 步，默认和本轮质量验收均为 20 步。
  FL2VA 用于 T2V/I2V，REF2VA 用于 R2V；沿用现有编码器、两套 VAE、`res_multistep/simple`、CFG 1。
- I2V 仍要求 `first_frame`，`last_frame` 可选，mode 仍是 `h3_i2v`。
  Director 内部选择 i2v/fl2v 不改变外部 mode，不开放尾帧单独输入。
- R2V 至少一项，最多 9 图/3 视频/3 音频；key 为 `ref_image_0..8`、`ref_video_0..2`、`ref_audio_0..2`，
  各类连续编号。构图按编号排序，素材描述列表重排不会改变引用编号。
- 图片 `LoadImage` → Group.ref_images；视频 `LoadVideo/GetVideoComponents` → Group.ref_videos；
  独立音频 `LoadAudio` → Group.ref_audios。Group 输出连接 Director.r2v_groups，再进入官方 conditioning 和采样。
- `referenceVideoAudio=True` 且规范化视频 `has_audio=True` 时，视频 components 的音轨连接同编号 ref_video_audio。
  关闭该选项只移除视频音轨，独立音频保留。
- 延续原生编号：`<Picture N>`、`<Video N>` 从 1 开始；**音频标签先数启用且实际有声音的视频音轨，再数独立音频**。
  上例视频音轨为 `<Audio 1>`，独立音频为 `<Audio 2>`。素材 key 仍从 0 编号，不能把标签与 key 混用。
- `refImageSize` 保留 match/max。原始 API 的输出始终接生成音轨；`sound=False` 继续由现有后处理移除音轨。
  声音是生成条件，不能保证逐字对白或精确复刻。
- 上传及规范化限制保留在能力表 `assets.uploadLimits`，素材超限、缺首帧、空参考、编号不连续、错误类型/路径、
  版本不可用、校验失败均在提交前报错，不静默丢弃。

## 最小插件加载与修补

固定上游 `AIMixer/ComfyUI_MiniMaxH3_Director@4c6245e518dd8a494f3afc4f3cccd53f22d82d10`。
迁移前核对两个本机副本：106 文件中 104 个与 Git 原始 blob 逐字节相同，原有两处修补保留。
本交付另外修复组合音频标签在规划层及执行层被错误删除的问题；最终相对上游共四个补丁：

- `director/audio_export.py`：静音轨按帧补齐。
- `nodes/director_common.py`：默认分段沿用全局提示词。
- `director/external_groups.py`、`director/executor_core.py`：音频标签按原生视频音轨优先的顺序核验。

补丁位于 `workflows/director-runtime/`；106 文件的 canonical-LF SHA256 位于 `director_plugin_manifest.json`。
只在一个新隔离副本中应用补丁并 audit，不覆盖本机原插件。最终 102/106 文件与固定上游完全相同。
已从固定上游 blob 重建一个全新 LF 副本，实际应用四个补丁并通过完整 manifest audit；
用于 GPU 的副本也通过同一个 audit。换行归一化只用于跨平台核验，不改动被审查的源副本。
已验证现有 ComfyUI 支持：

```text
--disable-all-custom-nodes --whitelist-custom-nodes ComfyUI_MiniMaxH3_Director
--disable-pinned-memory --disable-api-nodes --disable-auto-launch
```

保留动态显存，不加 `--disable-dynamic-vram`。验证实例各有独立 base/input/output/temp/user/SQLite，
只读取现有模型与锁定运行库；没有更新 Torch/ComfyUI，没有测试 Worker 连接生产 API。
未来对 8189 增加白名单仍需生产队列空闲和协调切换；本交付未执行该操作。

## 验收与交接后续

完整实测见 `workflows/validation/director-v1.0.0.json`；机器路径、媒体、原始日志与私有配置留在本地忽略目录。
原生与 Director 匹配 seed/settings 的 T2V 解码 RGB SHA256 相同；采样条件观测记录了非空图像/视频/PCM、
官方 `minimax_refs` 潜变量及后续 20 步采样，包含 `<Audio 2>` 保留的修补回归。
每个通过的样例检查原始 640×384、成品 640×360、124 帧、24fps、完整音视频解码、H.264/AAC、
faststart、静音导出及 JPEG 海报。MP4 沿用 SaveVideo 的 `outputs["8"].images` 元数据供现有 Comfy.result 下载。

本分支实际检查：Worker pytest **221 passed**、Ruff、JSON/可编辑图连接与控件检查通过，11 个原生基线文件未变。
没有修改 TypeScript/应用侧文件，本轮未重复执行应用候选的网页构建和浏览器测试。

| 最终插件 GPU 样例 | 生成、下载及验证总秒数 | 结果 |
| --- | ---: | --- |
| 文生 | 62.681 | 通过 |
| 首尾帧 | 69.253 | 通过 |
| R2V 图片 | 65.383 | 通过 |
| R2V 视频及其音轨 | 95.474 | 通过 |
| R2V 独立音频 | 62.971 | 通过 |
| R2V 图片、视频音轨、独立音频组合 | 103.430 | 通过，保留 `<Audio 2>` |
| R2V 关闭视频音轨 | 93.392 | 通过，无 video audio latent |

另实测首帧单独输入和明确声音的文生样例；后者平均 -23.7 dB、峰值 -3.5 dB。
匹配原生对照的红船文生样例两边声音都偏轻（平均 -51.4 dB），不据有 AAC 轨就宣称声音洪亮。
初始原生对照因系统内存提交压力解码失败，释放已空闲的模型缓存后重试通过。
另一次提前启动的自有隔离测试被主动取消，等待其他测试结束后重试；取消不计通过，见证据中的错误记录。

未验证范围：应用候选读取能力表后的端到端队列联调、M64 浏览器、G58 正式后台服务/重启生命周期、
实际生产 HTTP Range/播放/下载，以及 4 秒、长时长、高分辨率、满额 15 参考的全部 GPU 组合。
可编辑 JSON 已做连接和控件一致性检查，尚未做前端手工导入、再导出的往返验收。
12/30 步等参数有构图测试，本轮质量 GPU 档是 20 步。未接入 Turbo8/4、SelfLift、Semantic Bridge、FaceRefine 或二采。
不据缓存样例的运行时间宣称加速；新应用联调完成前不合并 main、不切生产。
