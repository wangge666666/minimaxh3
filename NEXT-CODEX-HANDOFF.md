# 下一位 Codex 接手：Director 画质升级

更新日期：2026-10-28（Asia/Taipei）。本文件是当前进度入口；较早的协作方案和候选交付文档保留历史时点描述。

## 当前已经完成

- 工作流候选：`codex/director-workflows`，`7d106504473b12379ac14bb98942c0c44efff530`。
- 应用候选：`codex/director-app`，`b640d4a0effa0c052a80abc339585c0fb2d3f9d7`。
- 整合运行代码：`190912e5286f5974d2da0d070ccb6a1331648eb1`，已合并 main。
- 已将该运行代码部署至生产，并明确启用三种 Director 模式；原生仍是默认入口，默认 20 步。
- 后续进度/方案/验收文档提交不改变上述运行代码。接手时读取 main 最新完整 SHA，不要停留在原应用候选或旧协作方案。
- 不可变基线 `v1.0.0` 仍指向 `318b0caa5a941b56e2a49e3f6b6e0e79ad017090`；11 个基线工作流文件未变。

### 已交付的接口

三个 mode：`h3_t2v`、`h3_i2v`、`h3_r2v`，均有
`workflows/h3_director_{t2v,i2v,r2v}_{api,mapping,editable}.json`。
能力注册表为 `workflows/h3_capabilities.json`。

Director revision 为 `director-v1.0.0`，媒体输出节点为 `["8"]`。
保留 `load_workflow(directory, mode, values)`；缺 engine 的旧任务使用 native。
服务端固定 revision/output，Worker 校验素材和完整工作流包；不可自动替换旧版本或降级重投。
已知 prompt 优先恢复原 prompt，而不是重新构图提交。

Web 的 Director 就绪要求显式开关、完整文件/hash/验收证据及目标 ComfyUI 节点/模型探测通过。
Worker 也有显式开关。配置已在生产启用；配置值与凭据只留在本地私有文件。

生产目标 ComfyUI 保留 `--disable-all-custom-nodes`，只白名单加载独立、经 manifest 核验的 Director 副本。
其他现存 ComfyUI 实例及其插件没有被覆盖。保留禁用 pinned memory、动态显存和共享 input/output。

## 已执行的验证

- TypeScript 80 项、Python 254 项、类型检查、Ruff、构建通过；生产目录再次构建及依赖完整性检查通过。
- 隔离环境：三种 Director 模式及原生兼容、图片/视频/音频分别与组合接线、Worker 原 prompt 恢复、重复提交防护、历史库副本与浏览器验证，见已有证据。
- 本轮生产：三个约 5 秒、640×360、124 帧、24fps、20 步任务通过生产 Web → 数据库 → 原生产 Worker → ComfyUI → 成品链路。
- 生产三种模式包含首尾帧及图片/视频/独立音频组合参考；每个任务仅提交一次，同 requestId 重试返回原任务。
- 生产成品通过完整音视频解码、H.264/AAC、海报、faststart、HEAD、前后缀 Range、ETag 与下载字节校验。
- 私网 HTTPS 的 health/state、三份新成品/Range/附件下载通过；16 份既有成品和 13 份既有海报经 HTTPS 下载逐字节一致。
- 原 25 条任务、14 项素材逐行/逐字节保留；新增三个已完成 Director 功能验收任务后共 28 条，19 completed / 6 failed / 3 canceled。
- 空闲状态下重启 Web、Worker 和目标 H3 后，28 条记录保留、三个 Director 任务的 prompt 信息仍在，未重新提交；后台任务、Worker 和三种 Director 就绪正常。
- 生产本机浏览器播放至结束无错误，实际下载与成品字节一致。
- 队列 500、并发 1、Mac 新图片生成关闭、历史图片可读；凭据/Worker 身份、其他 ComfyUI 实例、Tailscale 配置与网络路由保留。

公开脱敏证据：

- `workflows/validation/director-v1.0.0.json`：工作流 GPU 接线验收。
- `workflows/validation/director-integration-v1.json`：隔离应用整合验收。
- `workflows/validation/director-production-v1.json`：本轮生产部署与功能验收。

## 画质升级尚未开发

用户反馈现有片段多人脸崩坏、清晰度不足。功能验收通过不等于画质达标。
当前剧情样片为 360 档，逐字对白、口型与正式成片人脸质量尚未验收。
完整创作提示词、内置生图素材与三模式剧情样片保存在本地忽略目录，不在公开仓库。

按 [DIRECTOR-QUALITY-PLAN.md](DIRECTOR-QUALITY-PLAN.md) 推进：

1. **P0：人物参考、分镜和模式专用提示词编译。** 每镜一个主要说话人；保持角色/场景与素材编号；采用官方对白格式。换人、换场不默认继承上段人物条件。
2. **P0：高清质量基线。** 单人讲话、多人转头两种镜头 × 360/576/720 三档 × 三个 seed，20 步，共 18 条约 5 秒对照。API 允许更高参数不表示 GPU 画质已验收。
3. **P1：指定人物 FaceRefine。** 上游现有实现一次仅跟踪最大/居中一张脸；先做单人或指定对象、前后对比和丢失时明确跳过，不伪称自动修复全部人物。
4. **P2：H3 latent 放大及一次受控二采。** 对照直接高清生成；首尾帧保护单独验证；保留处理前版本。
5. 质量基线成立后再评估 Semantic Bridge、SelfLift 和 Turbo。不得把加速、修脸、语义桥和多遍二采一次全部默认开启。

新质量预设、FaceRefine、二采、语义桥、SelfLift、Turbo 均未在本轮接入或启用。
已有本机权重应先盘点、核验，不能重新下载现有模型或顺带升级 Torch/ComfyUI。

## 接手方式与生产同步

先阅读 `AGENTS.md`、`BASELINE-v1.0.md`、本文件、`DIRECTOR-QUALITY-PLAN.md`、
`DIRECTOR-INTEGRATION.md`、`WORKFLOWS-DIRECTOR-HANDOFF.md` 及修改目录的 AGENTS。
生产位置与私有启动/备份/证据路径见本地被忽略的部署记录，不上传该记录。

核对生产、已有独立工作流 worktree、整合 worktree 的 Git 状态和远程进度，保留已有修改。
继续使用已有独立开发位置；不要重建、覆盖或编辑旧解压副本。基于最新 main 在独立 worktree
使用 `codex/director-quality` 等新分支开发；若存在分支或工作区，先检查再续用。

工作流负责人维护工作流、构图、插件和 GPU 验收；应用侧质量档、选脸、对比、历史版本路由等接口需求先形成明确契约，避免重复改写。
新增增强包使用新 revision，保留旧完整包；现有系统不自动管理所有未来历史版本，目录路由需显式开发。

用户已要求通过验收的开发同步 GitHub 和生产。每个里程碑先做隔离测试与 GPU 画质验收，
再提交/合并、备份一致 SQLite/配置/journal，等待生产任务自然完成后受控部署，记录生产验收。
实验参数未验收时不在生产默认启用。测试 Worker 必须继续使用独立 API、数据库、端口和 state；
不得复制生产 journal 或从测试目录执行生产任务名的 hub 控制脚本。

## 仍未验证

- 物理 M64 浏览器、真实 OS 重启/重新登录后的完整自动启动。
- 所有时长/尺寸/比例、满额 15 项素材、12/30 步的 GPU 画质矩阵。
- 生成对白逐字正确、口型与人物时序质量；上述画质增强功能。
- 可编辑图的前端手工导入/再导出。早期隔离 ComfyUI 浏览器导航返回 403，未削弱来源保护。
- 本轮本机 Chrome 对私网 HTTPS 页导航超时；HTTPS 接口/媒体已通过实际 HTTP 客户端验证，浏览器播放下载实测使用生产 loopback 页面。不要混写成 M64 或 HTTPS 浏览器验收通过。
