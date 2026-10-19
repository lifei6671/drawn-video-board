# 画风及原参考库

分镜批准后运行 `style list --project ...`，返回原 CS Board 的 13 个预设、原配方及预览图。
使用 `style set --preset <原id>`，或 `style set --file <json>` 导入自定义 `name` + `recipe`。
旧的 lines/palette/proportions/shading/texture/composition/complexity 详细字段同样可用。
展示项目内画风预览和配置，经用户确认记录 style 批准。

预设图和原干净绘制手复制到项目。`project.json.config.pen_text` 使用原 make_branded_hand。
`canvas_hex` 为白板渲染底色，应与已批准画风一致。

单独风格参考可导入 `style/reference.png`；角色参考放 `characters/references/`。
需要多角色或不同命名时配置 project.json.visual_references，沿用原结构：

```json
{"style_image":"style/reference.png","characters":[{"id":"hero","name":"主角","description":"人物外形","images":["characters/references/hero.png"]}]}
```

`images prompts` 直接调用原 custom_reference_context/build_board_prompt；纸感隐喻和漫画
参考路由继续使用原参考库，选中的公共图片先复制到当前项目 style/references。
原角色与纯画风参考约束均保留，Skill 允许只给画风图而没有角色图。所有引用均为项目内相对路径。
修改参考图/配置会使画风批准及相关图片验收失效。视觉一致性仍需实际看图。
