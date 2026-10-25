# 可复用素材库

内置 25 项独立素材：原有 5 种气泡，加本次新增的 20 项。资源位于 `cs_board_video/assets/materials/`，
每项有透明 PNG、可缩放 SVG，以及 `catalog.json` 中的名称、分类、适用风格、朝向、建议前后层和安全排字区。
这些是项目原创矢量素材。人物剪影是通用形状，没有角色身份；选画风或导出素材都不会自动选角色。

| 分类 | 素材 id |
| --- | --- |
| 原有气泡 | speech-left, speech-right, thought, burst, caption |
| 新气泡 | speech-soft（无边框）, cloud-hand（手绘云朵）, shout（喊话）, sticky-note（便签）, torn-note（撕纸条） |
| 强调标记 | circle-mark, underline, highlighter, curved-arrow, bracket |
| 纸张边框 | paper-fiber, paper-newsprint, torn-paper, photo-frame, tape-strip |
| 分层物件 | moon, cloud, window-frame, leafy-branch, person-silhouette |

## 选择和导出

```powershell
python -m cs_board_video materials list
python -m cs_board_video materials list --category emphasis
python -m cs_board_video materials export --project content/demo --id curved-arrow --width 900 --height 600 --ink "#252521" --accent "#A8B88C"
python -m cs_board_video materials export --project content/demo --id speech-right --flip
```

`list` 无需项目。导出写入项目的 `materials/<id>.png/.svg/.json`，使用独立副本，不覆盖内置源资源。
默认 600×400，可用 `--width/--height` 改到64–4096；按指定画幅缩放，保持比例时使用3:2。
`--ink` 控制墨线，`--paper` 控制纸张/气泡填色，`--accent` 控制强调色；都使用 `#RRGGBB`。
`--flip` 水平翻转，元数据中的方向和排字区同步翻转。同名资源已有时明确报错，需要更新才加 `--replace`。
气泡轮廓可在 typography 内按需拉宽或拉高；导出时 SVG 和 PNG 使用同一份形状数据，但非等比缩放时线宽视觉可能略有差别。

## 在分镜里使用

新的五种气泡可直接作为 `visual_text[].presentation`，继承原字体确认、换行、溢出检查和逐字渐显/整句淡入。
分镜可以先用 `materials list` 查看预览路径、风格标签及朝向，再选择适合的气泡。
文字不要直接生成在气泡素材内，仍由本地字体排版。

强调标记、纸张和物件按需导出，用于构图或提供给合成工具。`depth` 是建议层级，素材本身没有自动运动或绘制顺序。
照片边框中间透明，纸张面和人物形状内部保留填色；报纸纹理只有抽象行纹，不伪造可读文章。
分层物件可分别放置、遮挡和动画，但本库不会把一张既有图片自动拆成图层，也没有新增多层时间轴。

## 维护

原始形状定义及生成入口为 `scripts/build_material_library.py`，复用 Pillow 和 SVG，不增加运行时依赖。
执行 `python scripts/build_material_library.py` 前设置仓库根目录到 `PYTHONPATH`。
它会更新新增气泡定义、素材目录内的默认 PNG/SVG 和 catalog；旧五种气泡 SVG 保持不变。
打包包含素材目录和新气泡 SVG；导出的项目副本及用户角色不随包分发。
