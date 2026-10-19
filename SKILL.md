---
name: drawn-video-board
description: >
  将中文口播文案制作成 CS Board 原生手绘视频的独立 Codex Skill。
  支持分镜、画风、生图方式、生成配音和完整动画预览的人工审核，
  项目素材隔离、本地 VoiceStudio 或本地模型配音、增量渲染及恢复。
  用于新建或继续白板手绘视频项目；不用于一般视频剪辑。
---

# Drawn Video Board

以本 Skill 的 Python CLI 执行确定性工作，Agent 负责创作、看图、试听和用户交互。
不启动 CS Board Web/FastAPI 服务，不调用原后台队列。
原项目全部源码在 upstream/，算法、13 种画风、参考库、标注编辑台、原 TTS、Remotion
和字幕合成均保留；对应关系见 [migration-map.md](references/migration-map.md)。
CLI 必须调用这些原模块，不另写替代算法。原 Web 是可选入口，Skill 不需要启动它。

## 执行入口

在 Skill 根目录运行 `python -m cs_board_video`（使用本项目 `.venv`）。
首次运行 `uv sync`，然后 `.venv/Scripts/python.exe -m cs_board_video doctor`。
Linux/macOS 的解释器为 `.venv/bin/python`。FFmpeg 和 ffprobe 需在 PATH。
所有命令说明见 [references/cli.md](references/cli.md)。执行位置与生产项目根目录不同时，
使用 `init --content <生产目录>/content` 和绝对的 `--project` 参数。

每次新视频先获得用户口播文案，然后 `init --name <slug> --script <文案文件>`。
继续项目先执行 `status`，需要自动推进时执行 `resume`。
`project.json` 是阶段与产物收据，`approvals.json` 是绑定摘要的批准记录。

## 必须遵循的顺序

1. **拆分分镜。** 保留原文，完整覆盖；按 [storyboard.md](references/storyboard.md)
   创建 `narration/storyboard.json`，运行 `storyboard validate`，展示整张分镜表。
   可用 storyboard request/adapt 获取原提示词并交回 Codex 候选，沿用原 make_plan 归一。
   停止并等待用户明确确认，再记录 `storyboard` 批准。
2. **确定画风。** 分镜批准后用 style list/set 选择原 13 种画风或自定义，按 [styles.md](references/styles.md) 保存配置，
   导入参考图和绘制手。展示画风，等待确认并记录 `style` 批准。
3. **选择生图方式。** 明确询问 Agent 生图或用户手动生图；运行 `image-mode set`，
   将用户选择记录为 `image_mode` 批准。未选择不得生成图片。
4. **准备并验收图片。** 按 [image-assets.md](references/image-assets.md) 用 images prompts 生成原每镜中文提示词，
   使用可用生图工具或交给用户手动生成。主图统一为 `scenes/scene-NNN/image.png`。
   使用图像工具时遵循当前可用工具的生图规范；保存实际提示词、生成来源与元数据。
   实际查看每张图，记录内容匹配、角色一致性、画风一致性、可绘制性的证据，
   再运行 `images review` 和 `images validate`。失败时逐镜反馈，保留已通过的资源。
5. **准备音频。** 按 [audio.md](references/audio.md) 校验用户音频与原文匹配，直接复用，
   无需重新批准。未提供音频则配置实际本地 VoiceStudio 或本地模型后 `audio synthesize`。
   新配音必须实际试听和原文比对，执行 `audio verify`，向用户提供试听文件，
   等待确认后记录 `audio` 批准。不得把技术探针当作听觉验收。
6. **制作真实绘制预览。** `timeline build` 使用原时长/字幕函数，`annotation build` 使用原标注生成器。
   实际看图检查，必要时按 [annotation.md](references/annotation.md) 用 drawing-plan.json 或原编辑台修正。
   原普通白板没有词级对齐时，字幕仍是估计，须审核节奏；精确镜头对齐可导入 audio/alignment.json。
   Remotion 项目先用 storyboard --narrative-only 审叙事，配音后 audio align，再 deck request/adapt
   调用原严格短语/PPT 规划，布局不得改变已批准的页数和口播；改变则重新审核分镜。
   原动态知识 PPT 必须真实词边界，禁止估计回退。运行 `preview render`、`preview compose`。
   按 [preview-review.md](references/preview-review.md) 展示完整预览、各镜时长、关键帧和报告。
   **停止并等待用户确认完整预览，之后才能记录 `preview` 批准。** 单镜确认不替代完整确认。
7. **正式渲染与交付。** `render --all` → `compose` → `validate`。
   交付 `output/final.mp4`、技术验收报告。字幕沿用原 FFmpeg 烧录，缺 libass 时用原 Pillow 回退。
   自动检查与用户视觉、听觉验收分别报告；不能把解码或摘要校验当作审美验收。

## 批准、修改与恢复

人工决策包括分镜、画风、生图方式、新生成配音、完整预览；交付后还需用户成片验收。
仅收到明确的“确认”“通过”“按这个来”等当前版本授权后才执行 `approve`。
先用 `review --stage ...` 获取当前摘要，把实际产物展示给用户。
批准时必须传入该摘要和用户确认原文。CLI 能校验版本与先后顺序，但不能证明对话身份；
**Agent 是对话授权的可信边界，不得自造用户回复。** `resume` 永远不写批准记录。
测试中的合成批准只用于隔离测试项目，不能写入真实制作项目。

用户要求修改时运行 `revise --stage ... --feedback ... [--scene ...]`，保留素材，
修改对应输入。任何文件内容变化都会使依赖它的收据/批准失效；不删除无关镜头文件。
分镜批准按镜头记录，单镜调整保留其他镜头的分镜批准。图片替换后要重新视觉验收。
更改标注顺序/时长/参数后必须重做受影响预览并重新批准完整预览。
正式编码 CRF 变更只重做正式视频；白板字幕配置影响合成，Remotion 字幕布局还影响原 props 和预览。
恢复从最后有效收据继续。

## 资源边界

全部任务输入、参考图、提示词、配音、标注、中间文件、日志、报告、最终视频都在
`content/<项目>/` 中。使用模板前先复制到项目。`asset`/`audio import` 可读取外部源文件，
但输出仅使用经过检查的项目内相对路径，拒绝绝对路径、`..` 和越界符号链接。
原文保留原始字节；导入/替换素材按内容摘要保留原件，不覆盖唯一原件。
`content/` 默认不进入 Git，不自动提交、推送或发布。
