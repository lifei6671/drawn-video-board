# CLI 与退出码

统一入口 `python -m cs_board_video`，成功返回 JSON `{"ok":true,"result":...}`。
退出码：0 成功；2 输入/资源错误；3 依赖或服务不可用；4 审核门槛未满足；5 执行失败。
`--help` 是 argparse 的普通帮助文本。所有项目命令都需 `--project content/<slug>`；
共享预设查询 `style list` 不需要项目。
运行前 `uv sync --locked`；锁定依赖见根目录 uv.lock。FFmpeg/ffprobe 为外部依赖。

```powershell
.\.venv\Scripts\python.exe -m cs_board_video init --name demo --script narration.txt
.\.venv\Scripts\python.exe -m cs_board_video storyboard import --project content/demo --file storyboard.json
.\.venv\Scripts\python.exe -m cs_board_video review --project content/demo --stage storyboard
# 向用户展示分镜并获得确认后，使用 review 返回的摘要与实际用户回复：
.\.venv\Scripts\python.exe -m cs_board_video approve --project content/demo --stage storyboard --digest <摘要> --user-message <用户确认原文>
.\.venv\Scripts\python.exe -m cs_board_video style set --project content/demo --file style.json
# 同样展示并批准 style；再询问和保存生图选择：
.\.venv\Scripts\python.exe -m cs_board_video image-mode set --project content/demo --choice manual
# 使用实际用户选择批准 image_mode，然后准备素材并查看图片。
.\.venv\Scripts\python.exe -m cs_board_video images digest --project content/demo --scene scene-001
.\.venv\Scripts\python.exe -m cs_board_video images review --project content/demo --scene scene-001 --digest <摘要> --evidence <实际看图证据>
.\.venv\Scripts\python.exe -m cs_board_video images validate --project content/demo
.\.venv\Scripts\python.exe -m cs_board_video audio import --project content/demo --source voice.wav --content-evidence <实际音频内容比对证据>
.\.venv\Scripts\python.exe -m cs_board_video timeline build --project content/demo
# 原标注生成器生成默认标注；实际看图后按需修正 drawing-plan 或原编辑台。
.\.venv\Scripts\python.exe -m cs_board_video annotation build --project content/demo
.\.venv\Scripts\python.exe -m cs_board_video preview render --project content/demo --resolution 960x540
.\.venv\Scripts\python.exe -m cs_board_video preview compose --project content/demo
# 展示 full-preview.mp4、review.json、contact.png，获得完整预览的用户确认并批准 preview。
.\.venv\Scripts\python.exe -m cs_board_video render --project content/demo --all
.\.venv\Scripts\python.exe -m cs_board_video compose --project content/demo
.\.venv\Scripts\python.exe -m cs_board_video validate --project content/demo
```

`review`/`approve` 的 stage 为 `storyboard|style|image_mode|audio|preview`。
分镜可用 `--scene scene-NNN` 按镜审核；完整预览不支持只批准单镜。
`asset --source <源文件> --dest <项目内相对路径> [--replace]` 导入资源并保存原件。
`audio synthesize` 按 audio/voice-config.json 调用本地服务；`audio verify` 实际内容比对后
更新证据，再获取新的 audio 摘要供用户审核。`audio import` 不需要配音批准。
`annotation build`、`preview render`、`render` 可指定 `--scene`；未指定则全部镜头。
`status` 派生当前有效检查点；`resume` 仅执行确定性阶段，遇创作输入或人工批准立即停止。
`revise --stage <阶段> --feedback <意见> [--scene ...]` 撤销对应审核并保留资源。

配置位于 project.json.config，默认见 [annotation.md](annotation.md)。编码 `crf` 范围 0..51，
字幕开关 `subtitles`，绘制手开关 `bare_tip`。改变配置后先 `status`，再 `resume`。
手动编辑 JSON 也会经过内容摘要与类型/时序校验；不要编辑 approvals.json 绕过审核。

## 原功能接入命令

| 命令 | 原能力 |
| --- | --- |
| storyboard request --duration 秒 [--narrative-only] | 提取原规划请求到 narration/plan-request.json |
| storyboard adapt --duration 秒 --file 候选JSON [--narrative-only] | 原 make_plan 归一 Codex 返回的数组 |
| style list | 全部 16 种内置画风及已保存的自定义预设，无需 --project |
| style set --preset id或名称 | 选用内置或自定义预设；自定义素材复制到当前项目 |
| style save [--name 名称] [--replace] | 保存已确认的自定义画风、参考图、绘制手和画布底色；不包含角色 |
| images prompts | 原风格、角色、参考图和构图提示词 |
| images fit / images key-text [--scene ...] | 原画幅适配 / 重点文字，保护原图 |
| audio align [--tokens 实际词边界JSON] | 原 Whisper 对齐 / 导入原格式 |
| deck request / deck adapt --file 候选JSON | 真实音频后原动态 PPT 规划；不能改变批准的叙事分组 |
| annotation preview / annotation import --scene ... --file ... | 原标注图与编辑台 / 导回校验 |

Remotion 初始 config 选 render_engine=remotion、fps=30；分镜先 --narrative-only，
配音后 audio align → deck request（读原提示词）→ deck adapt（提交模型数组）→ timeline build。
普通白板为 render_engine=whiteboard。原生画幅16:9/9:16/1:1均保留；预览规格应按项目比例设置。
Node 安装与原可选 Web 入口见根 README；原所有脚本在 upstream/，可按其原帮助单独使用。
