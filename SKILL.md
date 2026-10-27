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

## 模式选择

默认 `init --mode whiteboard`，已有项目继续使用原手绘流程。用户要求无画笔的独立图层动画时，
使用 `init --mode collage`，按 [拼贴动画](references/collage.md) 执行：
文案与原声核对 → `collage request` 规划表达和素材来源 → 准备素材、字体与真实时间轴 → `collage import/validate` → `collage` 计划确认 → 完整动画预览 → `preview` 确认 → 正式渲染。
每个元素独立保存，背景固定，前景按文案时码叠放与转场；不得将整幅分镜截图淡入当作多元素动画。
计划确认包含素材来源、画风、字体、文案时码与动画安排；用户当前已明确批准的样片方案可直接执行，不重复索取许可。
仍需遵循用户对新生图方式和新配音的选择，新增生成素材保存实际提示词与来源；用户原声可直接复用并记录对齐证据。
该模式不运行手绘的 `annotation`、画笔轨迹或逐镜完成图校验；技术验证、看图、听觉验收分别记录，完整预览确认仍是正式导出的前提。

## 手绘模式必须遵循的顺序

1. **拆分分镜。** 保留原文，完整覆盖；按 [storyboard.md](references/storyboard.md)
   创建 `narration/storyboard.json`，运行 `storyboard validate`，展示整张分镜表。
   手绘与拼贴的新分镜均填写 `visual_plan`：按文案选择直观、隐喻、幽默、反差、象征或夸张，解释关联理由，不强制逐字配图或搞笑。
   先盘点用户提供的图片和已有素材，判断是否需要联网检索；逐项规划 user/web/builtin/generate 来源、检索或生成要求、抠图需求及前后景安排。未知素材标待补，取得后记录实际来源与使用条件。
   照片去背景使用 AI 图像编辑，不安装或调用本地抠图模型；保留原图、实际提示词及结果，检查透明 alpha、主体保真和边缘。已有合格透明 PNG 直接使用，不把生成式编辑称为逐像素无损。
   可用 storyboard request/adapt 获取原提示词并交回 Codex 候选，沿用原 make_plan 归一。
   根据文案语义选择是否使用 A/B-roll：A 镜负责主叙事，B 镜补充物品、动作、环境、证据或图解。
   不机械交替，不为每句添加 B 镜；短辅助镜头可直接展示完成图，也可全屏手绘或画中画。
   使用可选 `roll` 字段并说明文案关联理由；返回 A 镜复用其完成状态，不重复生图和绘制。
   使用 A/B 的 request/adapt 候选逐镜提供原文 `text`，可按语义细分原固定分幕；普通分镜保持原流程。
   分镜表展示 A/B、展示方式、关联镜号和理由，协议见 [storyboard.md](references/storyboard.md)。
   仅在关键镜头设计可选 `visual_text`（关键词、关联句、内心话）；普通镜头留空，不逐镜堆字。
   文字与口播不必相同，但须说明关联依据。特别关键的概念可用 `visual_mode=text_only`。
   需要气泡、圈线、纸张或分层物件时，先查看 [materials.md](references/materials.md) 和 materials list；
   选用已有素材，按朝向、适用风格及安全排字区安排位置，人物角色仍独立选择。
   有文字时先按 [typography.md](references/typography.md) 从 `references/fonts` 选字体，
   用 typography font/sample 绘制实际排字样图，展示给用户确认并记录 `typography` 批准。
   字体与样图确认后，停止并等待用户明确确认分镜，再记录 `storyboard` 批准。
2. **确定画风。** 用 style list 查看 20 种内置画风（原 13 种加暖色Q版叙事漫画风、灰蓝写实叙事漫画风、暖纸松弛线描风、复古黑白线描风、灰调暖光漫画风、复古纸质人物拼贴风、纸框分层拼贴风）和用户保存的预设；分镜批准后用 style set 按名称或 id 选择，
   或按 [styles.md](references/styles.md) 配置新的自定义画风。预设会自动复制参考图、绘制手和画布底色到项目。
   暖色Q版叙事漫画风使用简化版预览图作为生图参考，配方采用封闭粗线轮廓、简化背景和大色块平涂，便于分区绘制。
   灰蓝写实叙事漫画风使用用户确认的简化版主图作为预览和生图参考，保留低饱和淡彩、自然比例与清晰线条。
   读取每镜 prompt-context.json 并把 references 对应图片实际传给生图工具。
   展示画风，等待确认并记录 `style` 批准。用户要求以后复用时，用 style save 保存已确认的自定义画风；
   后续项目可直接按名称选择，无需重复导入 JSON 和参考图。同名更新只在用户要求更新时使用 --replace。
3. **选择生图方式。** 明确询问 Agent 生图或用户手动生图；运行 `image-mode set`，
   将用户选择记录为 `image_mode` 批准。未选择不得生成图片。
4. **准备并验收图片。** 按 [image-assets.md](references/image-assets.md) 用 images prompts 生成原每镜中文提示词，
   使用可用生图工具或交给用户手动生成。主图统一为 `scenes/scene-NNN/image.png`。
   `roll.mode=return` 的镜头复用 `a_scene` 原图与已完成图层，不另行生图或验收重复图片。
   使用图像工具时遵循当前可用工具的生图规范；保存实际提示词、生成来源与元数据。
   实际查看每张图，记录内容匹配、角色一致性、画风一致性、可绘制性的证据，
   再运行 `images review` 和 `images validate`。失败时逐镜反馈，保留已通过的资源。
5. **准备音频。** 按 [audio.md](references/audio.md) 校验用户音频与原文匹配，直接复用，
   无需重新批准。未提供音频则配置实际本地 VoiceStudio 或本地模型后 `audio synthesize`。
   新配音必须实际试听和原文比对，执行 `audio verify`，向用户提供试听文件，
   等待确认后记录 `audio` 批准。不得把技术探针当作听觉验收。
6. **制作真实绘制预览。所有白板画风统一沿真实轮廓连续描线、沿用现有画笔左右往返、从上向下连续落色；颜色仅沿笔尖经过的圆头线段出现，抬笔移动不着色，禁止整行批量揭色、晕染、网格落块和末帧整块补齐。** `timeline build` 使用原时长/字幕函数，`annotation build` 使用原标注生成器。
   - 画笔默认马克笔；按用户要求用 `pen set --project ... --type fountain` 选择钢笔，用 `--type marker` 切回。钢笔按 sweety-handdraw-video 方法：生图时就准备真实细钢笔线稿，保留连续长轮廓与克制平涂，再整笔起收、转弯降速和抬笔。不能用旧粗马克笔画或照片换个手部图冒充钢笔画，禁止阈值重描、修补原画来假造笔迹；窗口不足时简化线稿，不跳笔补齐。预览和正式渲染共用选择，自定义预设保留画笔类型。切换后沿用原画风及预览审核流程，详见 [绘制画笔](references/pens.md)。
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

用户明确保存的可复用画风及素材位于 Skill 根目录 `style-presets/`，默认不进入 Git；
它是项目素材隔离的模板库例外，不保存项目角色或批准记录。选用时复制到当前项目，修改库不影响已有项目。
全部任务输入、参考图、提示词、配音、标注、中间文件、日志、报告、最终视频都在
`content/<项目>/` 中。使用模板前先复制到项目。`asset`/`audio import` 可读取外部源文件，
但输出仅使用经过检查的项目内相对路径，拒绝绝对路径、`..` 和越界符号链接。
原文保留原始字节；导入/替换素材按内容摘要保留原件，不覆盖唯一原件。
`content/` 默认不进入 Git，不自动提交、推送或发布。

后续所有存在前后遮挡的镜头，必须在分镜和素材准备阶段按实际深度规划任意数量的图层；每层完整描线并填色后才进入下一层。背景底图补齐被遮挡内容，前景使用对齐完整画布的透明 PNG，配置 layers/layer_id。不得让未填色前景变成白色剪影、让背景留下前景空洞，或把一层未完成的填色留到其他层之后。具体协议见 references/annotation.md。
