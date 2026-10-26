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
允许遮罩沿用原区域减后续区域/保护区。统一沿轮廓骨架描线、沿用现有画笔左右往返、从上向下直接填色；默认 96 笔、30fps、1920×1080。
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

所有白板绘制入口始终沿骨架追踪描线；填色沿用现有画笔，在轮廓范围内左右往返、从上向下推进，颜色只沿笔尖扫过的连续圆头线段出现，抬笔移动不着色。经过的像素直接使用目标颜色，不做晕染或羽化，支持灰色和黑色填充，不按饱和度
排除灰阶。每帧按路径弧长推进笔尖和落色，不按像素预算批量揭示整行或色块，取消区域结尾补齐和整张原图的末帧替换。因此遗漏
的主体或只安排了描线的主体会保持未完成状态，不会在片尾突然出现。应检查末帧及完整度报告。

可通过 `annotation import` 导入完整 JSON，或在数量与分镜 drawing_order 一致时使用
`drawing-plan.json` 覆盖元素。原矩形编辑台未提供轮廓编辑界面，不应依赖它编辑多边形。
未配置 `contours` 的旧标注仍用矩形约束范围、后续区域及保护区，但范围内的描线和填色也使用轮廓路径，不做矩形落块或整图末帧替换。

`ink_path` 统一为 `skeleton`，`color_fill` 统一为 `paint`。旧 `grid`、`contour`、`brush`、`contour-wipe` 配置及命令参数继续可读取，运行时归一为轮廓描线与现有画笔往返直接上色，不会恢复旧效果。路径提取失败或无墨迹时保留空帧与原时长，不回退分块绘制。更改算法使旧路径及视频缓存自动失效，已有项目需重做受影响预览并重新审核。
预览/正式共用原规范画布的布局 props，原渲染后通过 FFmpeg 缩放输出，避免低清重排构图。


## 任意场景按遮挡层级绘制

后续所有存在前后遮挡的场景，都按实际遮挡关系从后往前准备图层。层名和层数自由，例如远景、建筑、车辆、行人、近景枝叶，或墙面、家具、宠物、桌面物品；不绑定特定人物或植物类别。

每一层必须在自己的事件内完成“轮廓描线 → 画笔往返直接填色”，完成后才进入下一层。前景未填色区域保持透明，显示已完成的下层；真实白色物体仅在填色时逐渐变白。叶片间隙、门窗开口等由透明通道保留下层，不能挖成白纸。

分层素材必须是对齐到同一完整画布的 PNG，放在镜头目录下。第一层可用 RGB 或 RGBA；其余层必须是有透明区域的 RGBA。背景底图须补齐前景遮住的内容，人物、物件、动物等前景不携带背景。如果只有合成图，应先补绘独立背景并准备透明前景，再制作分层预览；渲染器不会从不可见像素推测背景。

在 drawing-plan.json 顶层提供 layers，或用 annotation import 导入如下标注。下面仅用三层举例，实际 layers 可以是任意数量、任意语义名称。

```json
{
  "canvas": {"width": 1920, "height": 1080},
  "sceneDurationMs": 9500,
  "layers": [
    {"id": "distant-building", "image": "layers/building.png"},
    {"id": "vehicle", "image": "layers/vehicle.png"},
    {"id": "near-branches", "image": "layers/branches.png"}
  ],
  "elements": [
    {"id": "building", "layer_id": "distant-building", "sequence": 1, "narrativeRole": "远景建筑", "subtitle": "建筑先完成",
     "region": {"x": 0, "y": 0, "width": 1920, "height": 1080}, "reveal": {"startMs": 0, "durationMs": 3000, "phase": "both"}},
    {"id": "vehicle", "layer_id": "vehicle", "sequence": 2, "narrativeRole": "中景车辆", "subtitle": "随后绘制车辆",
     "region": {"x": 0, "y": 0, "width": 1920, "height": 1080}, "reveal": {"startMs": 3000, "durationMs": 3000, "phase": "both"}},
    {"id": "branches", "layer_id": "near-branches", "sequence": 3, "narrativeRole": "近景枝叶", "subtitle": "最后绘制近景",
     "region": {"x": 0, "y": 0, "width": 1920, "height": 1080}, "reveal": {"startMs": 6000, "durationMs": 3000, "phase": "both"}}
  ]
}
```

layers 顺序即合成和绘制顺序，每层只对应一个事件；禁止拆成仅描线或仅填色的事件、交错顺序或并行时间。region 仅用于编辑定位，实际范围完全来自该层 alpha，不再减去尚未绘制的前景，也不叠加 contours、holes 或 protectedRegions。每层至少有描线和填色各一帧，正式工作流仍使用更严格的最短事件时长。

paths 缓存按各层自身线条提取；素材路径、顺序或任一 PNG 字节变化都会使相应镜头路径和预览收据失效。更改图层后必须重做完整预览，沿用原有预览审核流程。

上色直接使用现有画笔及手部素材，笔尖左右交替并从上向下连续移动；颜色只覆盖笔尖经过的线段，跨笔画时抬笔移动且不落色，不使用整行揭示、模糊、羽化、透明度渐增或扩散蒙版，也不新增笔刷资源。已有图层的半透明度仍按素材 alpha 正常合成。每层填色完成后才进入下一层。
