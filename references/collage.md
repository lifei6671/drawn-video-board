# 拼贴动画

适用于固定纸纹背景上逐渐出现人物、道具、文字的口播视频。背景与前景分开准备，每个可独立运动的对象都是一张透明 PNG；整张带背景的场景图无法自动拆成角色动画。

## 创建与素材准备

```powershell
uv sync --locked
npm --prefix cs_board_video/upstream/video_renderer ci
.\.venv\Scripts\python.exe -m cs_board_video init --name collage-demo --mode collage --script narration.txt
.\.venv\Scripts\python.exe -m cs_board_video collage request --project content/collage-demo
.\.venv\Scripts\python.exe -m cs_board_video materials list
.\.venv\Scripts\python.exe -m cs_board_video materials export --project content/collage-demo --id paper-fiber --width 1920 --height 1080
.\.venv\Scripts\python.exe -m cs_board_video materials export --project content/collage-demo --id collage-clock --width 1200 --height 800
.\.venv\Scripts\python.exe -m cs_board_video asset --project content/collage-demo --source voice.wav --dest audio/original/voice.wav
.\.venv\Scripts\python.exe -m cs_board_video asset --project content/collage-demo --source references/fonts/douyin.ttf --dest style/douyin.ttf
```

需要 Node、Chrome/Edge 或 Remotion 可用的浏览器。拼贴项目设为 `composition_type: collage`、`render_engine: remotion`，保持 30fps；旧项目缺少 `composition_type` 时使用原行为。不要直接切换制作中的手绘项目，用新目录创建拼贴项目。

图片支持 PNG/JPEG/WebP，前景推荐透明 PNG；字体使用项目内 TTF/OTF/WOFF/WOFF2。素材来源必须记录。可使用现有素材或用户素材；新生图及新配音按用户已选择的制作方式执行，不因切换模式自动调用生成服务。`collage prompts` 只导出已经导入计划的素材描述清单 `render/collage-assets.json`，不自动生成或抠图。

## 时间轴格式

### 怎样让人物叠在山川前面

使用三类独立素材，**让它们的可见区域重叠**；只把人物和风景左右并排，无法表现前后层次。

| 层 | 素材和设置 | 在画面中的作用 |
| --- | --- | --- |
| 固定底纹 | `background` 引用一张真实纹理图片 | 纤维、纸浆颗粒、磨损和压痕铺满画布，全片保持不动；米黄色底色不能替代纸纹 |
| 山川后景 | 普通 `image` 元素，示例 `z: 0` | 透明天空和不规则边缘露出纸纹，山川主体位于人物身后 |
| 人物前景 | 独立透明 PNG，示例 `z: 5` | 人物身体与山川重叠，遮住后方山体，独立入场和移动 |
| 物品前景 | 照片抠图 PNG，示例 `z: 6` | 书本等物品可以遮住山川或人物的局部，使用自己的动画时码 |

`z` 决定遮挡顺序，位置决定是否真正重叠；每层均可单独动画。后景也可以是完整照片，但不透明照片会盖住其范围内的纸纹。希望露出纸纹时，应使用去掉天空/外部背景的透明山川素材。跨转场保持的山川、人物不要加入会整体退场的组。

### 真实照片能不能抠成前景

可以。原照片 → 去背景/制作透明蒙版 → 保存带 alpha 的 PNG → 用 `asset` 导入 → 在计划中作为 `kind: image` 引用。渲染器不限制图片是拍摄、插画还是生成素材；透明部分露出下层，主体保持正常遮挡。不要把棋盘格背景保存成不透明图片，也不要用 JPEG 保存抠图结果。

当前 CLI **支持透明图片叠放，不内置自动抠图命令**。制作流程使用 AI 图像编辑去背景，再导入结果，不安装或调用本地抠图模型。已有合格透明图直接使用。保留原图、实际编辑提示词和结果；检查文字、产品细节、人物身份、透明 alpha、色边与漏抠。生成式去背景可能重建细节，不能称为逐像素无损抠图。山川、人物、物品分别保存，避免先合成一张大图后失去独立动画能力。

### 先规划表达和素材来源

`collage request` 在图片、音频尚未准备好时即可运行，输出 `narration/collage-request.json`，供 Agent 规划分镜。每个 beat 的 `visual_plan` 使用 [共同分镜协议](storyboard.md#表达与素材规划)，记录直观/隐喻/幽默/反差等手法及理由，逐项判断使用用户图片、联网检索、素材库还是新生成，记录是否需要 AI 抠图。素材来源与表达手法独立选择，照片也能用于隐喻和反差。

展示分镜时一并说明前后景、叠放和动画安排。确认可用素材后，取得文件、记录来源与使用条件，按真实音频对齐时码，才编写完整时间轴。规划阶段的 `reference` 是资料引用；渲染仍使用顶层 `assets` 中已导入的本地文件。`collage prompts` 导出已有计划的素材清单和各 beat 的表达计划，不自动联网下载、生成或抠图。

### 计划示例

下面是一个 **6 秒的格式示例**，音频、原文和实际时码必须相符后才能运行。原文为“事情悬在那里。既无法确定，也无法控制。”。用实际音频的 SHA-256 替换占位值；例如 PowerShell `(Get-FileHash content/collage-demo/audio/original/voice.wav -Algorithm SHA256).Hash.ToLower()`。

```json
{
  "schema_version": 1,
  "duration_ms": 6000,
  "audio": "audio/original/voice.wav",
  "font": "style/douyin.ttf",
  "alignment": {
    "source": "实际使用的 ASR 或人工对齐方式",
    "evidence": "记录逐词时码文件和核对结论，不能把示例时码当作真实对齐",
    "audio_sha256": "替换为实际音频 SHA-256"
  },
  "assets": {
    "paper": {"path": "materials/paper-fiber.png", "description": "固定米白纤维纸底", "source": "builtin-materials/paper-fiber"},
    "clock": {"path": "materials/collage-clock.png", "description": "透明背景复古闹钟", "source": "builtin-materials/collage-clock"}
  },
  "background": "paper",
  "beats": [
    {"id": "waiting", "start_ms": 0, "end_ms": 2200, "text": "事情悬在那里。", "visual_goal": "用摆动钟表表达等待"},
    {"id": "uncertain", "start_ms": 2200, "end_ms": 6000, "text": "既无法确定，也无法控制。", "visual_goal": "确定与控制按词入场"}
  ],
  "groups": [
    {"id": "old", "start_ms": 0, "end_ms": 5000, "exit": {"type": "fade", "duration_ms": 600}},
    {"id": "new", "start_ms": 4400, "end_ms": 6000, "enter": {"type": "fade", "duration_ms": 600}}
  ],
  "elements": [
    {
      "id": "clock", "kind": "image", "asset": "clock", "group": "old",
      "start_ms": 0, "end_ms": 5000, "x": 350, "y": 60, "width": 1200, "height": 800, "z": 1,
      "origin": [0.5, 0.1], "enter": {"type": "slide-down", "duration_ms": 500},
      "motion": {"type": "sway", "amplitude": 4, "period_ms": 2600}
    },
    {
      "id": "certain", "kind": "text", "text": "确定", "group": "old",
      "anchor": "uncertain", "offset_ms": 400, "end_ms": 5000,
      "x": 180, "y": 300, "width": 400, "height": 130, "z": 2, "font_size": 90,
      "enter": {"type": "pop", "duration_ms": 400}
    },
    {
      "id": "control", "kind": "text", "text": "控制", "group": "old",
      "anchor": "uncertain", "offset_ms": 1300, "end_ms": 5000,
      "x": 1340, "y": 520, "width": 400, "height": 130, "z": 3, "font_size": 90,
      "enter": {"type": "slide-left", "duration_ms": 400}
    },
    {
      "id": "next", "kind": "text", "text": "悬而未决", "group": "new",
      "start_ms": 4400, "end_ms": 6000, "x": 460, "y": 400, "width": 1000, "height": 160, "z": 4,
      "font_size": 110, "enter": {"type": "slide-up", "duration_ms": 500},
      "keyframes": {"scale": [{"at_ms": 0, "value": 0.95}, {"at_ms": 1500, "value": 1.05}]}
    }
  ]
}
```

时码规则：

- `duration_ms` 与真实音频时长一致。`beats` 按顺序完整覆盖原文，可保留语音停顿空隙，不能互相重叠。当前导入时校验文本覆盖和音频哈希/时长，**不会自动验证 ASR 是否听对**，仍须核对内容和边界。
- `start_ms` 或 `anchor + offset_ms` 二选一。`end_ms` 始终是从整段视频开始计算的绝对时间，不是元素持续时长。元素区间是 `[start, end)`，可以互相重叠。
- 所有时间只在编译时转成帧。关键帧 `at_ms` 相对**该元素的开始**，数值是该属性的绝对值；时间须严格递增，关键帧间线性插值，区间外保持端点。属性支持 `x/y/scale/rotation/opacity`。
- 位置尺寸为项目画布像素，`x/y` 是元素盒子左上角。`origin` 是盒内归一化旋转缩放中心，默认 `[0.5,0.5]`；带透明留白的素材仍以完整盒子计算。
- `z` 越大越靠前，同层级按元素声明顺序；字幕固定最上层。图片默认等比 `fit: contain`，也可 `cover`。
- `enter/exit` 支持 `none/fade/slide-left/slide-right/slide-up/slide-down`，入场额外支持 `pop`；`duration_ms` 默认 400，`distance` 默认 160 像素。左右滑入名称表示从哪一侧进入；上下滑入名称表示运动方向。退场按名称所指方向离开。
- `motion` 支持 `none/sway/float/spin`。`amplitude` 对摆动是角度、漂浮是像素；旋转每个 `period_ms` 一周。入场、循环、关键帧和退场可组合。
- `groups` 是可选的前景转场组；组内元素的时间必须位于组内。把旧组退场和新组入场安排在同一段绝对时间即可交叠，不缩短原声、不重启纸纹背景。背景覆盖层也只是一个低 `z` 的普通图片元素。
- `project.json.config.subtitles` 控制底部字幕；独立关键词 `kind: text` 不受它影响。

## 预览、批准与正式输出

```powershell
.\.venv\Scripts\python.exe -m cs_board_video collage import --project content/collage-demo --file collage-plan.json
.\.venv\Scripts\python.exe -m cs_board_video collage validate --project content/collage-demo
.\.venv\Scripts\python.exe -m cs_board_video review --project content/collage-demo --stage collage
# 展示计划、素材、字体和时码，使用实际用户确认及上一步 digest：
.\.venv\Scripts\python.exe -m cs_board_video approve --project content/collage-demo --stage collage --digest <digest> --user-message "<用户真实确认原文>"
.\.venv\Scripts\python.exe -m cs_board_video preview render --project content/collage-demo --resolution 960x540
.\.venv\Scripts\python.exe -m cs_board_video review --project content/collage-demo --stage preview
# 用户看过完整动画并明确确认后：
.\.venv\Scripts\python.exe -m cs_board_video approve --project content/collage-demo --stage preview --digest <digest> --user-message "<用户真实确认原文>"
.\.venv\Scripts\python.exe -m cs_board_video render --project content/collage-demo --all
.\.venv\Scripts\python.exe -m cs_board_video validate --project content/collage-demo
```

预览为 `previews/full-preview.mp4`，正式文件为 `output/final.mp4`。`preview compose` 返回已校验的完整预览；拼贴没有独立逐镜视频需要再拼接。预览尺寸必须保持项目比例，可直接用 1920x1080；竖屏项目指定例如 540x960。

`status/resume` 返回下一步；只有计划已批准且预览缺失时 `resume` 自动制作预览，不替用户确认。修改素材、文字、字体、时码或画幅后，原计划摘要/预览缓存自动失效；渲染代码变化也使预览缓存及预览批准失效。`revise --stage collage|preview --feedback ...` 撤销对应批准。

技术报告验证 H.264、帧率、尺寸、音视频时长和完整解码。看图检查前景顺序、遮挡、转场，听原声检查词句边界；技术通过不等于用户审美或听觉验收。当前不提供自动抠图、视频图层、骨骼动画、真实 3D、GUI 时间轴编辑，也不会自动从任意长音频可靠生成最终导演计划。
