# 分镜协议

关键镜头可增加独立的 `visual_text`，普通镜头不加字。支持直接排字、对话/思考气泡和纯文字概念页。
文字可提炼口播含义，也可提供相关的行动句，须记录关联理由；不可编造事实或冒充真实引语。
字段、字体选择及样图确认见 [typography.md](typography.md)。存在文字时，字体样图批准先于分镜批准。

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
