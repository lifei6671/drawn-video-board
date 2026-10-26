# drawn-video-board

基于原 CS Board 整体迁移的 Codex Skill。源版本
`f7780ef08cc2c752806e49805f5f696bfcd020de` 的 133 个 Git 跟踪文件保留在
`cs_board_video/upstream/`，内部结构保留。绘制算法统一由轮廓渲染器承担；项目 CLI 和原独立入口共用它。旧网格落块、整块擦除与整图末帧补齐已移除。

先看 [功能与模块对应表](references/migration-map.md)；逐文件来源和迁入摘要见
[upstream-manifest.json](references/upstream-manifest.json)。原许可证和原使用说明均保留。

保留原生白板绘制、原 13 种画风、角色/风格参考、重点文字、标注编辑台、原 TTS、
严格语音对齐、Remotion 动态知识 PPT、字幕烧录与 Pillow 回退、FFmpeg/PyAV 合并。
原 Web、队列和平台启动器保留为可选原入口。Skill 调用原函数，不启动 Web 服务或恢复队列。

新增适配仅围绕用户需求：`content/<项目>/` 隔离、分镜/画风/生图方式/新配音/完整预览
的版本审核、本地 VoiceStudio、共享路径预览和按镜头增量恢复。
自定义画风确认后可用 `style save` 保存到本地预设库；新项目通过 `style list` 查看、
`style set --preset "画风名称"` 选用，配方与参考图自动复制。详见 [画风与预设库](references/styles.md)。
现有 20 种内置画风。“暖色Q版叙事漫画风”使用简化版样图，配方适合分区手绘；“灰蓝写实叙事漫画风”保留自然比例、细线排线和侧光氛围；“暖纸松弛线描风”采用暖米白、橄榄绿、连续线描和简洁平涂。以上画风的预览图同时用作生图参考。新增“复古黑白线描风”，以黑白墨线和暖纸留白表现，画风样图与可选黑猫角色参考独立存放。“灰调暖光漫画风”采用灰色平涂、局部暖黄与充分留白，画风样图和可选男生角色参考也分别存放。

```powershell
uv sync --locked
.\.venv\Scripts\python.exe -m cs_board_video doctor
.\.venv\Scripts\python.exe -m cs_board_video init --name my-video --script narration.txt
```

需要 Python 3.11+、FFmpeg、ffprobe。原 Remotion 分支另需 Node、浏览器，并在
`cs_board_video/upstream/video_renderer` 执行原 `npm ci`。原可选 Web 前端依赖在
`cs_board_video/upstream/web` 按原 README 安装。Whisper 对齐沿用原模型和安装方式；
`audio align --tokens` 可导入已实际得到的原格式词边界。

入口：[SKILL.md](SKILL.md)。命令：[references/cli.md](references/cli.md)。
验收及未运行边界：[references/verification.md](references/verification.md)。

```powershell
$env:CS_BOARD_SOURCE='D:/wx_lifeilin/github.com/cs-board'
$env:CS_BOARD_REMOTION_TEST='1' # 已安装上述原 Node 依赖/浏览器时
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

迁入的原测试按原约定运行，见验收记录；Windows 的已知 macOS 夹具差异单独报告。
测试批准与测试词边界只是工程夹具，不能代表用户创作审核或真实语音对齐验收。
将本仓库链接到 Codex skills/drawn-video-board 即可调用。无自动提交、推送或发布。

关键镜头支持独立文字层：从 `references/fonts` 选字体，先生成样图让用户确认，再进入分镜批准。支持直接文字、十种气泡和纯文字页，普通镜头无需加字。详见 [文字与气泡](references/typography.md)。新增“复古纸质人物拼贴风”和“纸框分层拼贴风”；后者提供静态层次，独立视差运动另需分层素材。

内置 [51项可复用素材库](references/materials.md)：包含10种气泡、5种强调标记、5种纸张边框、5种基础分层物件，以及纸框分层拼贴风的6种日常用品、6种中外通用人物、10种动物和4种场景。`materials list` 查看预览，`materials export` 按尺寸和朝向导出透明PNG到项目；矢量素材另支持改色和SVG，不自动绑定人物角色。

白板绘制统一先沿真实轮廓连续描线，再沿用现有画笔左右往返、从上向下连续落色。颜色只出现在笔尖扫过的圆头线段内，抬笔移动不着色，不按整行或色块批量揭示。适用于所有画风及旧矩形标注；旧 grid/paint/brush/contour-wipe 参数仍可读取，统一执行此画法。算法更新会自动使旧路径与视频缓存失效，需要重新生成预览。详见 [绘制标注](references/annotation.md)。

画笔支持马克笔（默认）和钢笔。用 `pen list` 查看素材，`pen set --project content/demo --type fountain` 切换钢笔，`--type marker` 切回马克笔。钢笔参考 sweety-handdraw-video：准备真实细线原画，沿完整笔画压力起收、转弯降速与抬笔移动，保留原图墨线。预览和正式渲染共用选择。详见[绘制画笔](references/pens.md)。

分镜可按文案选择 A/B-roll：A 主叙事、B 全屏辅助镜头或画中画，以及返回已完成的 A 画面。辅助镜头可手绘进入或直接展示；普通分镜无需配置。原文、音频对齐和预览审核保持不变，详见[分镜协议](references/storyboard.md)。

存在遮挡的场景支持任意层数的独立 PNG 图层，按实际前后关系逐层完成描线和填色，未填色前景透出已完成的下层，支持半透明和开口。图层类型不限定人物或植物，详见 [分层绘制](references/annotation.md)。
