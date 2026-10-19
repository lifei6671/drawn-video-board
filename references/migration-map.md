# 原项目功能与模块迁移对应表

本表是本轮迁移基线。源仓库 `D:/wx_lifeilin/github.com/cs-board`，源 HEAD
`f7780ef08cc2c752806e49805f5f696bfcd020de`。原项目全部 Git 跟踪文件整体迁入
`cs_board_video/upstream/`，内部路径不变；不复制 `.git`、`.venv`、`.webapp`、
node_modules、缓存、密钥或用户任务数据。上游只有此一份实现，CLI 直接调用它。

此前交付为“两个渲染文件迁移 + 新写外围”，不作为完整迁移验收依据。
原渲染副本、另写的时间轴/标注/合成路径将收敛到迁入的原模块；审核和项目隔离是用户
明确新增需求，仅保留相应适配。原 Web/API/队列作为可选旧入口保留，Skill 运行不启动队列。

| 原有能力 | 原权威模块/函数 | 新位置（相对 upstream/） | 必要适配及接线 | 验证要求 |
| --- | --- | --- | --- | --- |
| 连续笔迹、骨架/网格、画笔/轮廓上色 | scripts/stream_render.py | 同路径 | 原样迁移，唯一算法来源 | 字节/AST 对比、原测试 |
| 区域遮罩、保护区、绘制手、笔画密度 | scripts/render_stream_whiteboard.py | 同路径 | 仅预览 writer/路径复用与空遮罩帧修复 | 逐帧回归、遮挡及预览/正式一致 |
| PyAV/FFmpeg 编码 | stream_render.transcode_h264 | 同路径 | 原实现保留 | 实际单镜编码 |
| 多幕合并及无 FFmpeg 时 PyAV 合并 | scripts/merge_scenes.py | 同路径 | 临时清单放本项目；CLI 调用原合并器 | 多镜头合并、回退测试 |
| 原 SRT 解析、按时长分组 | scripts/parse_srt.py | 同路径 | 直接保留原 CLI | 原输入/输出回归 |
| 标注图、中文标签、笔向 | scripts/render_annotation_preview.py | 同路径 | 直接生成项目内预览图 | 真实 PNG |
| 浏览器拖拽区域/时序编辑 | assets/preview.html | 同路径 | 原台保留；Skill 项目导出原命名配对文件 | 文件及编辑字段一致性；交互单独验收 |
| 本地重点文字叠加 | scripts/add_key_text.py、server.model_stage | 同路径 | 接入原文字处理，保留无文字选项 | 真正叠字 PNG |
| 普通图片及动态信息图绘制 | scripts/render_infographic.py | 同路径 | 保留原 CLI | 输入兼容、可用依赖检查 |
| 画风预设、自定义画风、预览图 | server.STYLE_PRESETS/BUILTIN_STYLE_DEFINITIONS/style_recipe | webapp/server.py、web/public/styles | 直接调用原画风库；用户确认后写项目快照 | 全部预设/图库对应，不减风格 |
| 纸感隐喻、漫画墨线参考选择 | paper_metaphor_reference_context/oil_visual_reference_context | webapp/server.py、assets/style-references | 直接复用原参考路由，使用前复制项目 | 原参考选择测试 |
| 用户风格及多角色参考 | custom_reference_context/build_board_prompt | webapp/server.py | 输入路径绑定项目，保留角色/风格分离约束 | 原提示词/角色回归 |
| 16:9、9:16、1:1、图片适配 | ASPECT_RATIO_SPECS/fit_image_to_aspect | webapp/server.py | 保留所有原画幅和适配函数 | 原画幅测试 |
| 分镜、普通场景归一、PPT 页面结构 | make_plan/normalize_standard_scene_count/normalize_deck_pages | webapp/server.py | Codex 可提交候选；原归一和校验继续使用；原 API 路径仍保留 | 原计划归一测试 |
| 多分镜拼图、原标注生成 | build_board_prompt/write_annotation/write_board_annotation | webapp/server.py | CLI 调原函数生成，再允许审核调整；不另造区域生成器 | 原字段/多面板回归 |
| 原模型 API 生图及独立生图工具 | generate_image/generate_standalone_image | webapp/server.py、web/app/image-generator | 原入口保留；Skill 支持 Codex/手动生成，使用同一提示词和素材协议 | 提示词函数实际接线，外部 API 不擅自调用 |
| 原 TTS 参数、Gradio/API、双节点 | synthesize_voice/_synthesize_voice_once | webapp/server.py | 保留原函数；新增本地 VoiceStudio 是适配，不替换删除原接口 | 原 TTS 测试、VoiceStudio 测试 |
| 中文发音规则 | pronunciation.yaml/preprocess_tts_text | 同路径 | 直接复用并在项目内保存生效副本 | 原发音规则测试 |
| 音频时长驱动普通分镜 | fit_scene_durations | webapp/server.py | 调原分配算法；不再用另写的预计时长权重算法 | 原边界/总时长测试 |
| Whisper 实际词边界、语音活动 | video_renderer/align.mjs | 同路径 | 仅缓存位置可绑定本项目，不改变对齐算法 | 工具可用时实测；缺依赖明确 UNAVAILABLE |
| 严格短语语音边界 | build_phrase_timeline | scripts/semantic_timeline.py | 直接调用；匹配不足失败，禁止比例估计替代 | 原 semantic_timeline 测试 |
| 页面/关键词与真实短语绑定 | build_deck_timeline | 同路径 | 直接调用原结构和校验 | 原全套语义/布局夹具 |
| 动态知识 PPT/信息图 | remotion_infographic_props、video_renderer/src | 同路径 | 原渲染器/构图/动画；同规范画布后缩放；Skill 单并发；整段预览批准 | TypeScript 构建、原夹具实际渲染、不同输出尺寸抽帧比较 |
| 原字幕拆句/真实字幕时间 | write_subtitles | webapp/server.py | 直接调用，不保留另写拆句器 | 原字数/时序输出对比 |
| 字幕烧录及无 libass 时 Pillow 回退 | _subtitle_video_input/_render_subtitles_with_pillow | webapp/server.py | 恢复原烧录，不以 MP4 隐藏文字轨替代 | 成片抽帧、FFmpeg/Pillow 路径 |
| 原进度、取消、失败重试、恢复、重渲染 | queue/job/checkpoint 系列函数 | webapp/server.py | 原入口完整保留；Skill 人工审核独立拦在调用前，不自动恢复旧队列 | 原 test_queue_resume.py |
| 音色/画风库 CRUD、历史/图库/下载/参数复用 | webapp/server.py 路由、web/app | 同路径 | 原 Web 可选入口保留；不得自动拷贝原用户数据库/配置 | 原测试及可选 Web 验收单独报告 |
| 启动器、macOS 打包、环境脚本 | start-webapp.*、启动白板工坊.bat、packaging、prepare_env.py | 同路径 | 保留原能力，原相对路径结构不改 | 源码校验；非当前平台构建 NOT_RUN |
| 使用示例、许可证、原测试及锁定依赖 | examples、LICENSE、tests、requirements、package-lock | 同路径 | 原样保留，新增测试不覆盖原测试 | 文件清单、摘要、原测试运行 |

## 本次明确增加的薄适配

- `content/<项目>` 隔离、原始资料保留、原子清单、互斥和按摘要增量复用。
- 分镜、画风、生图方式、新配音、完整预览的用户审核，绑定具体版本。
- Codex/手动生图交接、本地 VoiceStudio 接口与已有用户音频导入。
- 将已批准的项目数据映射到原函数的数据结构，不复制原业务算法。
- 原模块导入时关闭任务恢复/队列启动，仅限 Skill 使用；不改变原 Web 正常启动行为。

## 验收边界

每个文件记录来源摘要、迁入摘要及最小修改原因；每个接入点记录调用原符号。
原测试先迁移运行，再补本需求测试。文件存在不等于能力可运行；Node/Whisper、真实服务、
Web 交互和平台打包分别报告 PASS/FAIL/NOT_RUN/UNAVAILABLE，不沿用上一轮完成结论。
