# 绘制画笔

白板绘制提供 `marker`（马克笔，默认）和 `fountain`（钢笔）。钢笔使用黑色笔身、金色金属尖笔尖的透明持笔素材，适合线描和细节较多的画面；马克笔适合较宽的绘制轨迹。

```powershell
.\.venv\Scripts\python.exe -m cs_board_video pen list
.\.venv\Scripts\python.exe -m cs_board_video pen set --project content/demo --type fountain
# 切回马克笔：
.\.venv\Scripts\python.exe -m cs_board_video pen set --project content/demo --type marker
```

也可在初始化配置中指定 `"pen_type": "fountain"`。缺少此字段的旧项目仍按马克笔处理，不替换已有绘制手。`pen set` 明确替换项目的 `style/drawing-hand.png`，预览和正式白板渲染共用该选择。

钢笔采用用户指定的 sweety-handdraw-video 绘制方法，见[实现来源](sweety-fountain.md)。从原画准备开始使用细而流畅的真实钢笔线稿；提示词自动加入干净、连续墨线和克制平涂的要求。现有粗马克笔原画或照片须先重新准备适合逐笔绘制的线稿，不能只换手部图就称为钢笔画，也不使用边缘滤镜、阈值重画或修补原画的方式制造笔迹。

描线保留原始墨线颜色及抗锯齿边缘，采用参考实现的轮廓清理、细化、交叉点续接和微小碎线吸收；每笔有压力起收、曲线降速、平稳中段与独立抬笔移动。短到不能保持连续绘制的窗口会明确报出最少帧数，需简化线稿或在叙事允许范围内调整描线时间，不会跳笔补齐。默认马克笔揭示半径为 4 像素，钢笔为 2 像素，钢笔还按整笔弧长施加起收笔压力。

渲染不改写或重新风格化原画；上色保留已准备好的钢笔线稿，不会出现自动重描造成的灰斑、碎边或深色物体变形。两者均保持连续落色、抬笔不着色及逐层完成规则。

`bare_tip: true` 仍可隐藏手部，画笔类型继续控制绘制轨迹宽度。此选择只用于白板引擎，Remotion 分支不支持钢笔选项。

更换画笔会使当前画风批准和绘制缓存失效；按原有审核流程更新受影响预览。选择内置画风时保留当前绘制手；保存、恢复自定义画风预设时同时保留持笔素材和画笔类型，旧预设缺省为马克笔。`pen_text` 仅用于原马克笔的笔身文字，不应用于钢笔。

独立渲染脚本均支持 `--pen-type marker|fountain`。`stream_render.py --pen-image <PNG>` 以及 `render_stream_whiteboard.py` 的可选 `hand` 位置参数可以覆盖内置手部图片；画笔类型仍决定轨迹宽度。

## 素材来源

- 文件：`cs_board_video/upstream/assets/drawing-hand-fountain.png`，1080×1456 RGBA PNG，保留内置生成工具输出的原始透明通道和文件字节。
- 方式：内置 `image_gen`，以现有 `drawing-hand.png` 为握姿参考进行局部改笔，不使用外部图库。
- 提示词：

```text
Use case: precise-object-edit. Asset type: transparent hand overlay for a whiteboard drawing video renderer. Input image is edit target and pose reference. Replace only the broad white/brown marker with an elegant slim black fountain pen with a clearly visible exposed pointed gold metal nib, central slit and small breather hole, subtle gold trim. Realistic fountain pen, not ballpoint, brush pen or marker. Keep a natural photorealistic right hand grip, skin lighting, wrist direction and the overall pose and orientation of the original. Pen nib points toward the upper-left, hand and forearm extend lower-right with wrist cropped at bottom. Keep the very tip near the upper-left edge of the visible silhouette so automated top-left contact alignment works. Single hand holding single uncapped fountain pen, no extra objects, no cap, no paper, no text, logos or watermark. Isolated cutout with genuinely transparent background; preserve alpha. High resolution portrait composition and clean complete silhouette with comfortable transparent padding.
```

普通钢笔对透明分层素材先描完整主体边界，再补少量内部线条，避免人物或植物只剩几笔碎线。临时轮廓只用于描线阶段，上色恢复原图。钢笔上色采用约 0.6 秒内的 4 次快速左右往返，范围随主体大小调整并裁剪到本层；最终图像与透明孔洞保持不变。详见[钢笔绘制实现](sweety-fountain.md)。
