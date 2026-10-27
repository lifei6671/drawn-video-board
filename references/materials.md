# 可复用素材库

内置 51 项独立素材：25 项原创矢量素材，以及为纸框分层拼贴风新增的 26 项纸质剪贴位图。
资源位于 `cs_board_video/assets/materials/`。矢量素材提供透明 PNG 和可缩放 SVG；剪贴位图提供透明 PNG，保留复古印刷纹理和原色。
`catalog.json` 与 `collage-catalog.json` 记录名称、分类、适用风格、朝向及建议前后层。
人物均为通用虚构角色，不代表真实人物；选画风或导出素材都不会自动绑定角色身份。

| 分类 | 素材 id |
| --- | --- |
| 原有气泡 | speech-left, speech-right, thought, burst, caption |
| 新气泡 | speech-soft（无边框）, cloud-hand（手绘云朵）, shout（喊话）, sticky-note（便签）, torn-note（撕纸条） |
| 强调标记 | circle-mark, underline, highlighter, curved-arrow, bracket |
| 纸张边框 | paper-fiber, paper-newsprint, torn-paper, photo-frame, tape-strip |
| 分层物件 | moon, cloud, window-frame, leafy-branch, person-silhouette |
| 日常剪贴物品 | collage-kettle（水壶）, collage-teacup（茶杯）, collage-books（书本）, collage-phone（手机）, collage-clock（闹钟）, collage-chair（扶手椅） |
| 中国人物 | collage-cn-student（青年学生）, collage-cn-worker（维修工人）, collage-cn-elder（老年女性） |
| 外国人物 | collage-eu-teacher（欧洲教师）, collage-eu-reader（欧洲老年读者）, collage-af-researcher（非洲研究员） |
| 家养动物 | collage-duck（家鸭）, collage-dog（田园犬）, collage-sheep（绵羊）, collage-rabbit（兔子）, collage-cat（家猫）, collage-chicken（母鸡）, collage-cow（奶牛）, collage-horse（马） |
| 野生动物 | collage-lion（狮子）, collage-tiger（老虎） |
| 场景背景 | collage-farmyard（农家院）, collage-pond（池塘芦苇）, collage-woodland（林间空地）, collage-savanna（草原远山） |

新增素材统一使用浅色剪纸边缘、低饱和色和旧杂志印刷质感。查看 [素材预览](material-collage-preview.html) 和 [生成提示词与来源](material-collage-generation.md)。

## 选择和导出

```powershell
python -m cs_board_video materials list
python -m cs_board_video materials list --category emphasis
python -m cs_board_video materials list --category person
python -m cs_board_video materials list --category animal
python -m cs_board_video materials list --category scene
python -m cs_board_video materials export --project content/demo --id collage-duck --width 1200 --height 800
python -m cs_board_video materials export --project content/demo --id collage-pond --width 1920 --height 1280
python -m cs_board_video materials export --project content/demo --id collage-cn-student --width 1200 --height 800 --flip
python -m cs_board_video materials export --project content/demo --id curved-arrow --width 900 --height 600 --ink "#252521" --accent "#A8B88C"
python -m cs_board_video materials export --project content/demo --id speech-right --flip
```

`list` 无需项目。矢量导出写入项目的 `materials/<id>.png/.svg/.json`，位图导出为 `.png/.json`；使用独立副本，不覆盖内置源资源。
默认 600×400，可用 `--width/--height` 改到64–4096；矢量按指定画幅缩放，保持比例时使用3:2。剪贴位图始终等比缩放，居中放入目标透明画布，避免人物变形。
`--ink` 控制墨线，`--paper` 控制纸张/气泡填色，`--accent` 控制强调色；都使用 `#RRGGBB`。
上述改色选项仅适用于矢量素材；对剪贴位图指定其他颜色会明确报错。位图在 `list` 中的 `svg` 为 `null`，导出元数据 `colors` 为 `null`，只记录 PNG 哈希。
`--flip` 水平翻转，元数据中的方向和排字区同步翻转。同名资源已有时明确报错，需要更新才加 `--replace`。
气泡轮廓可在 typography 内按需拉宽或拉高；导出时 SVG 和 PNG 使用同一份形状数据，但非等比缩放时线宽视觉可能略有差别。

## 在分镜里使用

新的五种气泡可直接作为 `visual_text[].presentation`，继承原字体确认、换行、溢出检查和逐字渐显/整句淡入。
分镜可以先用 `materials list` 查看预览路径、风格标签及朝向，再选择适合的气泡。
文字不要直接生成在气泡素材内，仍由本地字体排版。

动物建议作为前景，场景建议作为背景；两者分别导出，按画面语义搭配。场景是框外透明、框内保留完整景色的纸框面板，未拆分树木、建筑或水面等内部图层。

强调标记、纸张和物件按需导出，用于构图或提供给合成工具。`depth` 是建议层级，素材本身没有自动运动或绘制顺序。
照片边框中间透明，纸张面和人物形状内部保留填色；报纸纹理只有抽象行纹，不伪造可读文章。
分层物件可分别放置、遮挡和动画，本素材库只提供素材，不会把一张既有图片自动拆成图层。独立元素的层级、时码和动画由[拼贴时间轴](collage.md)的 `elements/z/keyframes` 配置。

## 维护

原始形状定义及生成入口为 `scripts/build_material_library.py`，复用 Pillow 和 SVG，不增加运行时依赖。
执行 `python scripts/build_material_library.py` 前设置仓库根目录到 `PYTHONPATH`。
它会更新新增气泡定义、素材目录内的默认 PNG/SVG 和 catalog；旧五种气泡 SVG 保持不变。
打包包含素材目录和新气泡 SVG；导出的项目副本及用户角色不随包分发。
剪贴位图是内置 imagegen 生成的原始文件，独立登记在 `collage-catalog.json`；矢量生成脚本不改写这批图片或其清单。新增 PNG/JSON 已由现有打包通配规则覆盖。
