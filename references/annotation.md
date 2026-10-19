# 原绘制标注与编辑台

`timeline build` 后执行 `annotation build`，直接调用原 write_annotation 或多面板
write_board_annotation；保存原输出 annotation.upstream.json，再绑定项目镜头编号与时长。
单面板将原 200ms 起始停顿移到结尾；多面板结尾缩短 500ms，满足完整画面停留需求。
未另造按 weight 分配时间的算法。

Agent 必须实际看图检查原区域是否适合主体。需要修正坐标/顺序时，可提供逐镜
`drawing-plan.json`，只覆盖原标注相关字段：

```json
{"image_sha256":"当前图片 SHA256","visual_evidence":"实际看图的坐标依据","elements":[{"id":"person","label":"人物","narrativeRole":"角色","subtitle":"对应原文","region":{"x":20,"y":30,"width":400,"height":800},"protectedRegions":[],"reveal":{"durationMs":1500}}]}
```

elements 数量与原区域一致；坐标为源图整数像素。需要改变区域数量时同时修改该镜的
drawing_order 并重新审核分镜。生成的 annotation.json 支持直接精调 reveal 时间/方向/
上色参数，需连续 sequence、不重叠、正时长、末尾至少 0.5 秒；直接修改后重新预览审核。

`annotation preview [--scene ...]` 调原 render_annotation_preview.py，输出标注 PNG、
image.annotation.json 和项目 previews/editor.html。用原编辑台选择 image.png 与对应
image.annotation.json；导出后 `annotation import --scene ... --file ...`，校验后保留编辑。
真正浏览器拖拽交互与文件导出验收单独报告。

白板预览在正式画幅提取并缓存原路径，预览仅写帧缩小，故仍承担正式像素绘制成本。
允许遮罩沿用原区域减后续区域/保护区。默认骨架、96 笔、轮廓扫描上色、30fps、1920×1080。
Remotion 使用原 page/cue 时间轴与 React 动画，路径缓存记录原 props，不套用白板遮罩检查。
预览/正式共用原规范画布的布局 props，原渲染后通过 FFmpeg 缩放输出，避免低清重排构图。
