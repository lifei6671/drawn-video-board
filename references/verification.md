# 本轮整体迁移验收

日期：2026-10-19（Asia/Shanghai）。本记录取代此前“两文件迁移+新外围”的验收结论。
旧基准不自动视为当前实现通过；本轮新产物前缀 migration-。

| 项目 | 结果 | 实际证据 |
| --- | --- | --- |
| 完整迁移来源 | PASS | 原133个跟踪文件全部存在，128个字节不变，5个有说明的最小修改；所有原Python函数/类保留；upstream-manifest.json |
| 唯一原算法接线 | PASS | 新CLI调用原 make_plan、style/build_board_prompt、fit_scene_durations、write_annotation/write_board_annotation、write_subtitles、merge、compose、semantic_timeline、Remotion；旧重复engine删除 |
| 原Python套件 | 46 PASS / 1 ERROR | 47项，0.229秒；upstream-tests-final.log。唯一失败为macOS目录选择夹具在Windows拒绝/tmp/video-output；未改原仓库同样失败，original-tests.log。未跳过或削弱原测试 |
| 既有需求测试及逐帧回归 | PASS | 25项，87.277秒，无跳过；adapter-tests-final.log。包括六镜头、恢复/增量、批准门禁、缓存篡改、路径/锁、原20帧逐像素一致 |
| 新迁移测试 | PASS（7项，无跳过） | 最终完整套件23.067秒，migration-tests-complete.log；原画风/提示词/规划、原标注编辑台导出/叠字/字幕、Gradio下载边界、PyAV/Pillow、Remotion语义依赖、真实渲染闭环、133文件/AST来源；覆盖实际Remotion生图提示词在叙事/已有deck两阶段的主体字段 |
| Remotion不同尺寸预览一致性 | PASS | 正式640×360/预览320×180，共用原规范布局props，5组对应帧缩小后平均像素误差<5；实际完整预览批准门禁→正式合成，22.487秒 |
| 原Remotion夹具 | PASS | 原1920×1080/30fps/60帧夹具实际渲染，remotion-native/native.mp4；原TypeScript npm run build通过 |
| 原前端构建及SSR | PASS | 原web npm run build通过；node --test tests/rendered-html.test.mjs 3项通过；不是浏览器完整业务验收 |
| 当前六镜头MP4 | PASS | content/migration-six-scenes/output/final.mp4，640×360/15fps/12秒，合成测试音、工程批准，最终报告与收据匹配 |
| 真实生图/本地配音素材接入 | PASS（复用真实素材） | content/migration-agent-assets/output/final.mp4；复用此前实际image_gen与VoiceStudio indextts2输出，重新查看图片并经本轮迁移链渲染；没有声称本轮重新调用模型 |
| VoiceStudio当前连通性 | PASS | doctor --voice-url http://127.0.0.1:13900，OpenAPI和实际模型可读；doctor.json。模板化模型列表路径返回404独立标UNAVAILABLE，不影响实际/v1/models |
| VoiceStudio协议与审核 | PASS | 本地HTTP夹具实际调用，生成配音未确认不能推进；原Gradio参数及项目下载目录通过mock边界测试，不表示真实Gradio服务联调 |
| 原Whisper真实音频对齐 | NOT_RUN | 保留原align.mjs/模型协议；语义流程用明确的合成测试词边界，不能当真实声学对齐或口播验收 |
| Wheel与独立安装 | PASS | 从显式清单的干净源码快照构建，149条目/133原文件摘要一致；不含node_modules、dist、旧engine、用户配置、缓存；独立环境site-packages实际加载13画风，wheel-check.json及installed-smoke-final.log |
| Skill及退出协议 | PASS | quick_validate.py：Skill is valid；缺cv2的python -S调用返回JSON code=3；git diff --check通过 |
| 原Web实际交互、原外部模型API、真实Gradio、macOS打包 | NOT_RUN | 原入口/源码保留，不以文件存在或SSR代替运行验收 |
| 用户听觉/视觉验收 | NOT_RUN | 所有工程批准都标记合成测试，不能替代用户制作批准 |

实际修复而非重写：完全遮挡区域写足帧；PyAV多片PTS连续；Gradio下载在项目内。
原规划提示词/最终合成仅提取共享函数，Web仍调用同一函数。原Web恢复与队列默认保持，
Skill导入不启动任务。原普通字幕估计逻辑保留，动态PPT坚持真实词边界、低覆盖失败。

复验过程中Remotion高并发曾报localhost页面无响应；一次同条件重试仍失败。单页诊断
实际渲染成功，因此Skill明确使用单页并发，原Web默认50%不变。低清预览先保持原规范
布局渲染，再由FFmpeg缩小，未修改原React构图。最终不同尺寸回归通过，早前失败日志保留。

字幕沿用原FFmpeg烧录，缺libass时Pillow回退；不是隐藏文字轨。白板开启绘制手时，未来
区域像素检查标REQUIRES_VISUAL_REVIEW；Remotion遮罩NOT_APPLICABLE。技术通过不证明观感。
全部测试音频/参考图/中间产物在content内，构建依赖另在忽略的开发目录。无提交、推送或部署。
