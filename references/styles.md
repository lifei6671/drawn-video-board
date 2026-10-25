# 画风及原参考库

运行 `style list`，返回 20 个内置预设（原 13 个及新增的暖色Q版叙事漫画风、灰蓝写实叙事漫画风、暖纸松弛线描风、复古黑白线描风、灰调暖光漫画风、复古纸质人物拼贴风、纸框分层拼贴风）、本地自定义预设、配方和参考图路径。
列出预设不需要项目或分镜批准；原 `style list --project ...` 调用仍可用。
分镜批准后使用 `style set --project ... --preset <id或名称>`，或 `style set --project ... --file <json>` 导入自定义 `name` + `recipe`。
旧的 lines/palette/proportions/shading/texture/composition/complexity 详细字段同样可用。
展示项目内画风预览和配置，经用户确认记录 style 批准。

预设图和默认绘制手复制到新项目。默认手为透明背景的白杆棕色笔素材，内置渲染入口使用同一张图；已有项目和自定义预设保存的绘制手保留不变。`project.json.config.pen_text` 使用原 make_branded_hand。
`canvas_hex` 为白板渲染底色，应与已批准画风一致。

单独风格参考可导入 `style/reference.png`；角色参考放 `characters/references/`。
用 `asset --project ... --source <图片> --dest style/reference.png [--replace]` 明确导入时，
会重新启用这张画风图，包括此前选择无参考图预设而停用过参考图的项目。
需要多角色或不同命名时配置 project.json.visual_references，沿用原结构：

```json
{"style_image":"style/reference.png","characters":[{"id":"hero","name":"主角","description":"人物外形","images":["characters/references/hero.png"]}]}
```

`images prompts` 直接调用原 custom_reference_context/build_board_prompt；纸感隐喻和漫画
参考路由继续使用原参考库，选中的公共图片先复制到当前项目 style/references。
原角色与纯画风参考约束均保留，Skill 允许只给画风图而没有角色图。所有引用均为项目内相对路径。
修改参考图/配置会使画风批准及相关图片验收失效。视觉一致性仍需实际看图。

## 保存为跨项目预设

自定义画风在当前项目确认并记录 style 批准后，可以保存一次，以后直接选择：

```powershell
.\.venv\Scripts\python.exe -m cs_board_video style save --project content/demo --name "暖纸黑线漫画"
.\.venv\Scripts\python.exe -m cs_board_video style list
# 新项目分镜批准后：
.\.venv\Scripts\python.exe -m cs_board_video style set --project content/next-video --preset "暖纸黑线漫画"
```

`--name` 可省略，默认使用当前自定义画风名称；也可用保存返回的 `custom-...` id 选取。
名称不能与内置画风名称/id 冲突，`custom-` 前缀保留给 id。同名保存默认报错；
用户明确要求更新时加 `--replace`，新内容仍须先在来源项目获得画风批准。
内置预设直接选择即可；`style save` 仅用于自定义配置。

保存内容包括完整画风配置、画风参考图（如有）、绘制手图片和 `canvas_hex`。
角色参考、项目文案、音频、批准记录不会进入库。没有参考图的文字配方也能保存。
原详细字段会补出等价 recipe，后续提示词仍使用原 CS Board 生图模块。

库固定保存在实际 Skill 安装目录的 `style-presets/`（与当前工作目录和项目目录无关），
`library.json` 保存索引，`assets/` 保存素材副本，默认忽略 Git；备份或迁移时复制整个目录。
库不会依赖来源项目中的文件，删除来源项目不影响预设。更新时原子替换索引并保留旧素材，
失败不会发布半套预设；并发保存使用文件锁。

选择自定义预设会将配方、参考图及绘制手复制到目标项目，并同步画布底色。
项目已有角色配置保留；选择无参考图的预设会停用旧的画风参考，旧文件仍保留。
修改库不会改变已选用它的项目；要更新项目需再次执行 style set，再审核发生变化的画风。
选用预设不自动批准画风，已有分镜、画风和生图方式的审核顺序不变。

## 暖色Q版叙事漫画风

内置 id：`builtin-warm-chibi-story`，名称：`暖色Q版叙事漫画风`。

配方默认用于先描轮廓、再分区上色的彩色手绘动画原画：

- 奶油黄与浅杏色背景，蜂蜜金、橙棕和焦糖色为主；深褐近黑色粗描边，轮廓连续，主要形状形成封闭色块。
- 二维赛璐璐大面积平涂，每个物体一种底色加最多一层块面阴影，极少量简单高光和椭圆投影；减少渐变与反光，不画颗粒、木纹或排线。
- 人物约 2.5 至 3 头身，圆脸大头、短手短腿，表情鲜明；头发、衣褶、手部和机械零件简化，保留叙事所需的识别细节。
- 只保留必要人物和道具，用动作、对比或具体物件隐喻表达观点；背景纯色或极少空间线条，主体周围留白，边界清楚，预留字幕区。
- 人物身份、年龄和故事物件服从当前文案，不固定复用女孩、机器人或工作间。输出完整彩色原画，不画步骤图、对比拼图、画外绘制手或画笔；禁止文字、数字、Logo、水印、品牌标签、摄影写实、3D塑料感和霓虹配色。

图片位于 `cs_board_video/upstream/web/public/styles/warm-chibi-story.png`，使用 2026-10-25 生成并经用户确认的
“女孩修理机器人”简化版样图，保留生成文件原始字节；同一份图片同时承担预览和生图参考。

```powershell
.\.venv\Scripts\python.exe -m cs_board_video style set --project content/demo --preset "暖色Q版叙事漫画风"
```

选用后，预览图复制到项目 `style/preset-preview.png`，同时注册为项目画风参考；画布底色设为 `#FFF7D6`。
`images prompts` 将参考图复制进项目并写入每镜 `prompt-context.json.references`，画风配方与参考图约束同时进入提示词。
原 Web 的首次生图、单页重新生图和独立生图页也会使用此内置参考；内置画风在 Web 库改名后仍按固定 id 关联内置图片。
用户明确导入自己的画风参考时，使用项目参考。
已选用预设的项目保留自己的配方和参考图；需要新版时重新执行 `style set`，再确认更新后的画风。

## 灰蓝写实叙事漫画风

内置 id：`builtin-blue-gray-story`，名称：`灰蓝写实叙事漫画风`。

- 配色：低饱和灰蓝、灰绿、暖米白，搭配浅褐木色和自然肤色，少量暗青色点缀。
- 人物：自然写实比例，五官概括但结构可信，通过眼神、手势与姿态叙事，情绪按文案调整。
- 线条与上色：深灰或深褐细线，轻微笔压变化；头发、衣褶和暗部使用稀疏短排线，哑光淡彩色块与大块明暗塑造体积，保留轻微纸感。
- 光影与场景：自然侧光或窗光，暖色受光面与灰蓝阴影形成冷暖对照；日常物件与人物动作关联，透视自然，保留必要背景和字幕留白。
- 约束：人物身份、性别、年龄、服装、情绪和场景服从文案，不固定复用男子、手机、账单或餐桌。禁止复制信封文字、衣服标志，以及文字、数字、Logo、水印、漫画边框和对白框；避免 Q 版大头、粗黑卡通描边、高饱和配色、摄影写实及 3D 塑料渲染。

主图位于 `cs_board_video/upstream/web/public/styles/blue-gray-story.png`，使用 2026-10-25 生成并由用户选定的
“街边修理自行车”手绘简化版，保留生成文件原始字节，同时用于预览和生图参考。

```powershell
.\.venv\Scripts\python.exe -m cs_board_video style set --project content/demo --preset "灰蓝写实叙事漫画风"
```

选用后复制预览图和完整配方到项目，将同一图片注册为画风参考，画布底色设为 `#A7B9B9`。
`images prompts` 的每镜参考清单以及原 Web 首次生图、重新生图和独立生图入口均使用该参考图。
内置画风在 Web 改名后继续按固定 id 关联素材；用户提供的项目参考与角色设定优先。

## 暖纸松弛线描风

内置 id：`builtin-warm-paper-line`，名称：`暖纸松弛线描风`。

- 暖米白纸色背景，橄榄绿、奶油白、深暖褐，少量桃色腮红与赭黄；保留原参考图的温柔松弛感。
- 外轮廓中等粗细，内部线条更细，轻微笔压变化；轮廓连续、主要色块封闭，适合先描轮廓再分区上色。
- 约 3 头身的圆润人物，点状眼睛和小鼻口；简化碎发、衣褶与手部，平涂为主，每个物体最多一层简洁阴影。
- 背景留白，省去纸张颗粒、擦笔、密集排线和复杂光照；去掉原图书法文字、对白框和思考气泡，避免干扰语义分区。
- 人物身份、年龄、动作、情绪及场景按文案重画，不固定复用女孩、托腮坐姿或三花猫。

主图位于 `cs_board_video/upstream/web/public/styles/warm-paper-line.png`，由内置 imagegen 工具依据用户参考图
于 2026-10-25 生成手绘简化版，保留生成文件原始字节；同一张图用于预览和生图参考。
样图已检查无文字与气泡，尚未进行完整手绘动画的视觉验收。

```powershell
.\.venv\Scripts\python.exe -m cs_board_video style set --project content/demo --preset "暖纸松弛线描风"
```

选择后复制完整配方及参考图到项目，画布底色设为 `#FFFCF0`；每镜提示词均携带配方与项目内参考图。
沿用现有画风审批和项目素材隔离规则，Web 的生图、重新生图与独立生图也使用同一参考。

## 复古黑白线描风

内置 id：`builtin-retro-mono-line`，名称：`复古黑白线描风`。

- 暖米白纸色底 `#FAF3E3`，黑色墨线、少量黑色平涂与纸色留白，无彩色、灰阶阴影或渐变。
- 连续封闭轮廓，外线略粗、内线更细，轻微笔压变化；不使用排线、网点、颗粒和做旧纹理。
- 约 4 头身的概括造型，四肢宽度足够，减少手指线、纽扣、衣褶和装饰，适合先画轮廓与五官再快速填黑。
- 人物物种、身份、服装和表情服从文案及独立角色参考；不会自动带入猫耳、尾巴、尖牙或固定职业。

画风样图：`cs_board_video/upstream/web/public/styles/retro-mono-line.png`。
采用“人物浇花”的单幅插画展示画风，避免猫的身份特征污染风格参考。由内置 imagegen 于 2026-10-25 生成，保留原始字节。

```powershell
.\.venv\Scripts\python.exe -m cs_board_video style set --project content/demo --preset "复古黑白线描风"
```

选用后，只有画风样图会复制为项目预览及画风参考；未配置角色的项目不会自动新增猫角色。
该画风沿用现有审批、参考图传递及 Web 生图链路。2026-10-25 的 12 秒无声猫店员绘制预览已获用户确认；该确认仅针对本次绘制效果，不代表其他分镜或正式成片验收。

### 独立角色参考：黑猫店员

猫的三视图单独存放在 `cs_board_video/upstream/assets/character-references/retro-cat/turnaround.png`，
同目录 `character.json` 是可加入项目 `visual_references.characters` 的角色条目模板，不是画风配置。
三视图由内置 imagegen 依据用户原图生成，保留尖耳、半眯竖瞳、小尖牙、弯尾及黑背心，
移除围裙图案，减少纽扣与衣褶，加宽腿部。角色表情可随剧情变化；实际分镜只画所需角度，不照搬三视图排版。

仅在需要这只猫的项目中执行：

```powershell
.\.venv\Scripts\python.exe -m cs_board_video asset --project content/demo --source cs_board_video/upstream/assets/character-references/retro-cat/turnaround.png --dest characters/references/retro-cat.png
```

随后将 `character.json` 中的对象追加到项目 `project.json.visual_references.characters` 数组，
保留现有 `style_image` 和其他角色，不覆盖整个 `visual_references`。
模板的 `images` 路径对应上述导入目的地；库内资源不能直接作为项目外路径引用。
角色添加或修改后重新审核画风，再生成提示词；提示词将画风图与角色图分别声明。
猫也可搭配其他画风使用：选择有参考图的画风，或单独导入该画风的参考图，并保留角色条目。

## 灰调暖光漫画风

内置 id：`builtin-gray-warm-comic`，名称：`灰调暖光漫画风`。

- 暖灰白底 `#F7F5EF`，黑色手绘轮廓、浅灰和中灰平涂，局部淡暖黄点缀。
- 主要形状封闭，简化衣褶、手指和物件细节，头发保留宽阔留白，减少实黑面积。
- 背景充分留白，光照简化为小块平涂；先画轮廓与表情，再画必要道具环境，最后少量填色。
- 人物身份、服装、表情和场景由文案及独立角色参考决定，不固定使用男生、沙发、手机或台灯。

画风样图位于 `cs_board_video/upstream/web/public/styles/gray-warm-comic.png`。
用无人沙发与台灯展示线条、灰色块和暖光，避免男生身份混入画风参考。
由内置 imagegen 于 2026-10-25 生成并保留原始字节；生成提示词见 [gray-warm-comic-generation.md](gray-warm-comic-generation.md)。
已检查静态样图，尚未制作或验收该画风的动画预览。

```powershell
.\.venv\Scripts\python.exe -m cs_board_video style set --project content/demo --preset "灰调暖光漫画风"
```

选择画风只导入画风参考，画布底色设为 `#F7F5EF`，不会自动添加男生角色。

### 独立角色参考：短发男生

角色三视图位于 `cs_board_video/upstream/assets/character-references/gray-warm-boy/turnaround.png`，
同目录 `character.json` 是现有 `visual_references.characters` 格式的可选角色模板。
保留原图的微乱短黑发、圆脸、简洁五官和浅色翻领衬衫；灰长裤与休闲鞋是对原图未展示部分的简化补全。
参考图包含正面、四分之三侧面和背面，分镜仅使用所需角度，表情随故事变化。

仅在需要该男生的项目中导入：

```powershell
.\.venv\Scripts\python.exe -m cs_board_video asset --project content/demo --source cs_board_video/upstream/assets/character-references/gray-warm-boy/turnaround.png --dest characters/references/gray-warm-boy.png
```

随后将 `character.json` 中的对象追加到 `project.json.visual_references.characters`，保留 `style_image` 和其他角色。
角色添加或修改后重新审核画风，再生成提示词；画风图与角色图会分别声明。
可保留此角色并改选其他画风，不把角色模板绑定到本预设。

## 复古纸质人物拼贴风与纸框分层拼贴风

`builtin-vintage-paper-people`：粗纤维纸底、复古写实人物剪贴、低饱和半色调，适合人物关系、心理话题与行动句。
`builtin-layered-paper-collage`：纸框、景物面板、跨框前景与浅投影形成层次。单张图可以复现这种视觉层次；月亮、人物、背景分别运动需独立透明图层，本次没有新增多层视差渲染器。

该画风可从 [素材库](materials.md) 选择 26 项独立透明剪贴 PNG，覆盖 6 种日常用品、6 种中外通用人物、10 种动物及 4 种纸框场景背景；用 `materials list --category person` 查看人物，`materials export` 导出项目副本。选择画风不会自动套用具体人物或道具。

两者参考图不绑定人物身份，也不内嵌文字。用 [typography.md](typography.md) 本地排字和气泡。颗粒纸纹作为底材，不把网点拆成大量笔画。素材与生成来源见 [paper-collage-generation.md](paper-collage-generation.md)。
