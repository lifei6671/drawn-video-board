# 分镜协议

## 表达与素材规划

手绘和拼贴都先设计画面如何表达观点，再准备素材。新分镜在每个 scene（拼贴为 beat）中填写 `visual_plan`；旧项目省略此字段仍可使用。`storyboard request/adapt` 会提示并保留它，素材提示词也会带上该计划。

选择纸框分层拼贴风时，先读[纸框拼贴导演规则](paper-collage-directing.md)：按论点与关系划分连续场景，再把原文短语对应到场景内部的增量变化。不能把每句口播机械转换为一张新图。该规则的导演表是规划文档，不是额外的 JSON 字段或新审批阶段。

```json
{
  "visual_plan": {
    "devices": ["metaphor", "humor", "contrast"],
    "reason": "用遥控器控制海浪却毫无效果，表达想控制一切的徒劳；这是比喻画面，不是真实事件",
    "assets": [
      {"subject": "手持遥控器的人", "source": "user", "brief": "待补：用户如有合适人物照片可提供，否则改为生成素材", "cutout": true},
      {"subject": "海浪后景", "source": "web", "brief": "检索海岸海浪照片，选择视角匹配、使用条件明确的图片", "cutout": false}
    ]
  }
}
```

- `devices` 可组合 `literal` 直观、`metaphor` 隐喻、`humor` 幽默、`contrast` 反差、`symbolism` 象征、`exaggeration` 夸张。按语义和情绪选择，不逐字配图，不强制搞笑或机械轮换手法。
- `reason` 解释观众如何读懂画面及其与文案的关联。不得改变原文结论、编造事实或让隐喻冒充事件实录。
- `assets` 逐项记录 `subject` 主体、`source` 来源、`brief` 选择要求、`cutout` 是否去背景；纯文字镜头可为空列表。来源为 `user/web/builtin/generate`，一镜可混用；先盘点用户图片和已有素材，再判断是否需要联网寻找具体人物、地点、物品或历史照片。
- `web` 的 `brief` 写检索词和筛选条件，`generate` 写生成要求。已确定来源可补 `reference`（项目内路径或原始网页 URL）。用户尚未提供、尚未找到的素材标为待补，不虚构文件或链接。取得图片后记录原始页面、使用条件及项目内文件；计划引用不会自动下载或导入。
- 需要抠图时使用 **AI 图像编辑**，不安装或调用本地抠图模型。保留源图、实际提示词和编辑结果，输出真正带 alpha 的透明 PNG，检查主体、文字、脸部、边缘和漏抠。已有合格透明图直接使用。生成式编辑可能重建细节，不宣称逐像素无损。

分镜表同时展示原文、表达手法、画面设计、关联理由、素材来源、抠图需求及前后景/动画安排。联网检索由 Agent 按需执行，不要求每镜联网；真实照片也能用于隐喻和反差。手绘仍按画风与绘制要求准备图层；照片原貌及独立动画优先采用拼贴模式。A-roll 返回镜复用已完成画面，不能通过新素材计划改变该画面。

## 原文与镜头字段

关键镜头可增加独立的 `visual_text`，普通镜头不加字。支持直接排字、对话/思考气泡和纯文字概念页。
文字可提炼口播含义，也可提供相关的行动句，须记录关联理由；不可编造事实或冒充真实引语。
手绘模式的字段、字体选择及样图确认见 [typography.md](typography.md)，字体样图批准先于分镜批准。
拼贴模式使用 [collage.md](collage.md) 的 `kind: text` 和本地字体，字体及文字布局纳入拼贴计划确认，不混用白板 `visual_text` 或另建 `typography` 批准阶段。

用户原文原样保存 `narration/original.txt`。Agent 创作分镜，不用字符切分器替代叙事设计。
将下列 JSON 保存到 `narration/storyboard.json` 或用 `storyboard import --file` 导入：

```json
{"scenes":[{"scene_id":"scene-001","narration":"这里填写连续的原文。","narrative_goal":"解释核心关系","visual_description":"左侧人物把球递给右侧人物","composition":"两人分居两侧，中间留白","subjects":["人物甲","人物乙","球"],"drawing_order":["人物甲","球","人物乙"],"estimated_duration":8,"transition":"cut"}]}
```

编号从 scene-001 连续；镜头口播拼接必须等于原文（只忽略空白）。预计时长单位秒，
仅为创作参考，正式时长由原时长/对齐函数按实际音频确定。v1 支持硬切，其他转场拒绝并明确提示。
执行 `storyboard validate` 后展示全部字段。分镜可以按镜头批准，但进入画风阶段前
全部镜头都要有有效批准。单镜改动保留其他镜头的批准。

可用 storyboard request --duration 秒 输出原 CS Board 规划提示词，Codex 按提示词给出原数组，
再 storyboard adapt --duration 秒 --file 候选.json，经原 make_plan 归一后保存上述协议。
保留原字段到各镜 upstream。多面板原结构可存 upstream_panels；不丢原叙事与布局信息。
Remotion 初始叙事规划加 --narrative-only，实际配音/词边界就位后用 deck request/adapt
做原 PPT 布局规划，保持批准的每页原文分组；需要重新分组时返回分镜审核。

存在前后遮挡时，drawing_order 按实际层级从后往前安排，每项表示该层完整的描线和填色，不能先画完所有线稿再统一填色。任意物体、场景和层数都适用，具体图层协议见 annotation.md。

## 可选 A/B-roll 编排

白板引擎支持 `roll`。省略时保持原普通手绘流程，不强制每段使用，也不改变原文。
Agent 根据文案判断：主角、主场景和核心观点用 A；具体动作、物品特写、环境、证据或图解用 B。
只有辅助镜头能补充信息时才切换；单一动作、短句或连续因果不必额外切镜。不能虚构文案未提供的事实。

在普通分镜字段之外增加以下对象；示例按 A → B → A → B → A 排列：

```json
[
  {"type":"a","mode":"draw","reason":"建立人物与庭院主场景"},
  {"type":"b","mode":"hold","a_scene":"scene-001","reason":"说到果实时展示果实特写"},
  {"type":"a","mode":"return","a_scene":"scene-001","reason":"回到人物继续主线"},
  {"type":"b","mode":"draw","layout":"inset","box":[0.6,0.06,0.34,0.34],"a_scene":"scene-001","reason":"在主场景旁补充植物结构"},
  {"type":"a","mode":"return","a_scene":"scene-001","reason":"以主场景收束"}
]
```

- `type`：`a` 主叙事、`b` 辅助镜头。`reason` 必填，解释与本镜口播的关联。
- `mode`：默认 `draw` 沿轮廓绘制；`hold` 直接展示完成图；`return` 仅用于 A 镜，直接复用原 A 实际绘制结束的画布，包括独立图层和原文字，不另加 `visual_text`。
- `a_scene`：B 镜与返回镜必填，引用之前已经建立的 A 镜；不能指向未来镜头、B 镜或另一返回镜。省略 `roll` 的普通镜也可作为原始 A 镜。
- `layout`：默认 `full` 全屏；B 镜可用 `inset`，背景为关联 A 镜的完成画面。`box=[x,y,w,h]` 可选，默认右上角 `[0.6,0.06,0.34,0.34]`；数值归一化、区域不得越界，w=h 且至少 0.05，以保持原画幅比例。

返回复用的是**A 镜实际结束时的画布状态**，不支持在一笔中途暂停再续画。未安排绘制的内容保持未出现，不会用完整原图补齐。原始分辨率的无手画布按输入版本缓存；缓存缺失时沿原绘制路径重放至末态，不从低分辨率预览截图。B 镜可短暂直接显示，不必每次从白纸开始。
所有镜头仍分别使用对应原文片段，合成时配音连续、画面硬切；不能为了返回 A 而重复其口播。
预计时长仍为参考，实际镜长依据音频对齐。Remotion 暂不接受 `roll`，会明确报错。

`storyboard request` 会给出以上选择原则。采用 A/B 的 `storyboard adapt` 候选须逐镜提供原文 `text`、`title`、`elements` 和可选 `roll`，允许按语义细分原固定分幕；这些 `text` 拼接必须完整等于原文。无 `roll` 时仍沿用原 make_plan 规则。
直接 `storyboard import` 也接受 `roll`。分镜表应展示类型、展示方式、关联镜号及选择理由；沿用整体验收，不增加每次切镜确认。

`hold` 和 `return` 自动生成无绘制元素的标注。`return` 不需要本镜 `image.png`，复用 A 镜已验收的素材。修改 A 镜图像、独立图层、标注或文字后，引用它的 B 镜和返回镜缓存及完整预览验收都会失效；无关镜头可继续复用。
