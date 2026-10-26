# 图片生产和验收

`image-mode set --choice agent|manual` 后仍需记录用户选择的批准。
每个镜头路径：`scenes/scene-NNN/prompt.md`、`image.png`、`image-metadata.json`。
例外：A/B-roll 的 `roll.mode=return` 返回镜无需独立图片和图片检查记录；提示词会注明复用哪个 A 镜，其原图、图层与文字由原 A 镜提供，沿用原图视觉检查。其他 A/B 镜仍须正常准备和验收自己的主图。
画中画 B 镜图片只画辅助镜头本身，不预先把主场景或画中画边框拼入图片；合成器按分镜位置叠加，完整预览时检查是否遮挡重要内容。
`images prompts` 直接使用原 build_board_prompt，包含已批准的画风、构图、主体和角色参考约束。
Remotion 尚未配音/生成 deck 时，将批准叙事的原 elements 映射为原插图字段；有 deck 后使用
该页原 illustration_elements 与布局，防止叙事阶段的主体在提示词中丢失。
源图不生成字幕、乱码、水印；可用原 images key-text 叠加重点文字，字幕由原合成器烧录。

手动模式给用户逐镜完整中文提示词和准确目标绝对路径，等用户资源就位。
读取每镜 `prompt-context.json.references`，将其中项目内相对路径解析为图片并实际传给生图工具；
手动模式也应交付这些参考图，不能只交付文字。
Agent 模式调用当前可用生图工具，保存实际提示词；工具输出先导入项目，
另存 `scenes/scene-NNN/generation.json`，记录实际工具、模型（如可知）、时间和来源。
不得声称未实际调用的工具已生图。

PNG 必须可解码、背景不透明，短边至少 64 像素且比例相符；空白图拒绝。
沿用原图片适配能力，低于正式尺寸报告 upscale_required，由用户检查放大质量。
`images fit` 使用原裁切/缩放，`images key-text` 使用原本地文字算法；原图保留 image.source.png，
派生图改变后重新看图验收，不覆盖唯一原件。已有主图被用户替换时应先用 asset 导入保护版本。
Agent 实际看图检查：内容符合分镜、人物一致、画风一致、主体边界与线条便于绘制。
获取 `images digest --scene ...`，再运行 `images review --digest ... --evidence "逐项看图证据"`。
此命令记录 Agent 的视觉判断，不是用户批准，也不执行视觉模型。
最后 `images validate` 写逐镜报告，未通过镜头保持待修正状态。

替换已有素材必须显式 `asset --replace`；新旧原件按摘要保留在项目内
`render/cache/imports/`。不能覆盖原始口播、状态和审核文件。

有遮挡的场景必须额外准备独立背景底图与透明前景，按实际深度组织任意数量的图层，不能把前景留白洞当作背景。每层 PNG 对齐同一完整画布，并生成 image.png 合成参考图；独立素材保存在 scenes/scene-NNN/layers/，路径和绘制顺序写入 drawing-plan.json 顶层 layers 与元素 layer_id。逐层核对遮挡、透明边缘和下层完整度，再使用分层预览确认。单张图不能提供被遮住的背景，需独立补绘并记录实际来源。
