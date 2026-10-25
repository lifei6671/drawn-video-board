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

## 按主体轮廓绘制

需要按人物、手机、家具等完整主体绘制时，给每个元素添加 `contours`（多边形并集）和可选
`holes`（从并集中扣除的遮挡区域）。坐标为源图整数像素，每条多边形至少三个点且面积大于零。
`region` 仍保留为编辑定位用的外接矩形，实际绘制范围以轮廓为准。主体轮廓须根据原图标注，
渲染器不自动识别人或物件；相邻主体应明确归属，不能把背景一并框进人物。

```json
{
  "id": "person-ink",
  "sequence": 1,
  "narrativeRole": "人物",
  "subtitle": "人物看手机",
  "region": {"x": 10, "y": 10, "width": 80, "height": 80},
  "contours": [[[10, 10], [90, 10], [50, 90]]],
  "holes": [[[43, 25], [57, 25], [57, 40], [43, 40]]],
  "reveal": {"startMs": 0, "durationMs": 3000, "phase": "ink", "protectedRegions": []}
}
```

同一标注文件的所有元素均须采用轮廓模式。`reveal.phase` 支持 `ink`（只描线）、`color`
（只填色）、`both`（默认，先描线再填色）。可为同一个主体安排两个不同 id 的事件，复用
同一组轮廓：先依次绘制人物、手机、沙发、台灯的线稿，再按主体安排填色事件。各事件时间
不能重叠，结尾仍需至少 0.5 秒停留；已画轮廓不会被后续填色事件从允许范围中扣除。

轮廓模式始终沿骨架追踪描线；填色采用主体内部往返笔触，支持灰色和黑色填充，不按饱和度
排除灰阶。每个像素分配到逐帧填色预算，取消区域结尾补齐和整张原图的末帧替换。因此遗漏
的主体或只安排了描线的主体会保持未完成状态，不会在片尾突然出现。应检查末帧及完整度报告。

可通过 `annotation import` 导入完整 JSON，或在数量与分镜 drawing_order 一致时使用
`drawing-plan.json` 覆盖元素。原矩形编辑台未提供轮廓编辑界面，不应依赖它编辑多边形。
未配置 `contours` 的旧标注维持原矩形遮罩和填色行为。
预览/正式共用原规范画布的布局 props，原渲染后通过 FFmpeg 缩放输出，避免低清重排构图。
