# 关键镜头文字与气泡

文字是独立于底图的排版层，使用本地真实字体，既不让生图模型画字，也不改口播原文。
只在概念、转折、内心话或行动提示等关键镜头采用。普通镜头省略 `visual_text` 或用空数组；没有文字的旧项目不增加字体确认。
关联句可不同于口播，必须在 `purpose` 写清关联依据，不得编造事实、统计数据或冒充真实引语。

## 分镜字段

```json
{
  "visual_mode": "illustration",
  "visual_text": [{
    "text": "把期待变成行动",
    "purpose": "把自我改变的口播提炼成行动提示，属于编辑概括",
    "presentation": "speech-right",
    "animation": "characters",
    "box": [0.06, 0.18, 0.55, 0.28],
    "font_scale": 0.055,
    "color": "#202020",
    "fill": "#FFFFFC",
    "start": 0.65,
    "duration": 0.25
  }]
}
```

`box` 为画幅归一化 x/y/宽/高；`font_scale` 是画幅高度比例，0.02–0.3；每镜最多三条，每条最多120字。
长句自动换行，缺字或溢出会报错，不静默截断，不自动换字体。可显式用换行符分行。
`start`、`duration` 为镜头实际时长比例，结束不晚于95%，保留阅读停留。分镜时根据口播含义安排，当前不自动做词级同步。
`presentation` 支持 `plain`（直接排字）、`speech-left`、`speech-right`、`thought`、`burst`、`caption`。
另有 `speech-soft`（无边框）、`cloud-hand`（手绘云朵）、`shout`（喊话）、`sticky-note`（便签）、`torn-note`（撕纸条），都带安全排字区。
`animation` 默认 `characters`：完整字形依次渐显，按总 duration 分配每个字的出现时长。
`fade`：整条文字及气泡一起淡入。两者都使用 ease-out，不描笔画，绘制手只用于底图。
短标题可用整体淡入，关联句可逐字渐显；根据叙事选择，不要求每镜都有文字。

关键概念页可设 `visual_mode: "text_only"`，只画标题或解释句。必须仍保留该镜口播、叙事目标等必填分镜字段。
纯文字页可用 `typography background` 生成底图，不需要 AI 生图。仍需正常图片内容检查、标注与预览验收。
本功能接入原生 `whiteboard` 渲染路径；Remotion 使用原有 deck 文本节点，不混用本字段。

## 字体选择与样图确认

在分镜阶段执行，先做样图，再记录字体和分镜批准：

```powershell
python -m cs_board_video typography fonts
python -m cs_board_video typography font --project content/demo --font tiejili
python -m cs_board_video typography sample --project content/demo --scene scene-001 --background background.png
python -m cs_board_video review --project content/demo --stage typography
```

展示 `previews/typography-sample.png`，说明字体名称、选词理由与使用镜头，等待用户明确确认后才用
`approve --stage typography --digest <当前摘要> --user-message <用户原话>` 记录批准，再确认整份分镜。
没有背景可先生成纸底排字样图。已存在场景图时会自动用该图，也可以传入同比例背景。
样图按真实字体和全分镜文字验证；更换文字、布局、字体文件、画幅、渲染实现或样图后原批准失效。
项目内保存字体副本，字体源变化不影响已经选择的项目，重新选择才更新。

默认字体来源为本仓库 `references/fonts`。TTF/OTF 直接解析，WOFF/WOFF2 复用 [FontTools](https://github.com/fonttools/fonttools)
解包，不另写字体转换器。可变字体可加 `--weight 700`，必须处于字体支持范围。
安装 wheel 的用户用 `--directory <字体目录>` 提供字体；字体没有随 wheel 分发，不宣称其商用许可。

## 气泡资源与绘制质量

`cs_board_video/assets/bubbles/` 内有十个透明 SVG 与同源 `templates.json`，可复用或修改颜色和尺寸。
这些气泡和其他强调、纸张、分层素材统一收录在 [materials.md](materials.md) 的25项素材库中。
JSON 的轮廓及安全排字区供本地渲染，SVG 供其他工具复用。底图提示词会预留排字区域并禁止生成文字和气泡。
文字和气泡一起参与最终帧比对、预览缓存失效；叠字场景的底图区域泄漏检查明确标为需要视觉复核，不能以像素检查替代遮挡验收。
