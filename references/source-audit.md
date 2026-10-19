# 迁移边界与来源审计

原项目 HEAD：`f7780ef08cc2c752806e49805f5f696bfcd020de`；目标起点
`a3802bb4784543afc0f3c49920d43141e3befdfb`。原仓库除已授权 CodeGraph 索引外未修改。

此前两个引擎文件加自写外围的交付已被本轮整体迁移取代，不能沿用旧验收结论。
完整对应表见 [migration-map.md](migration-map.md)，133 个原文件的源/迁入摘要和修改原因
见 [upstream-manifest.json](upstream-manifest.json)。128 个文件逐字节不变，5 个原文件
仅做接线或经实际回归证明必要的修复。原有函数/类均保留，新增来源测试核对 AST。

原模块保持唯一实现：

- `bridge.py` 绑定项目路径、原数据结构和 Codex 候选 JSON，不实现规划/提示词算法。
- `workflow.py` 实现用户明确要求的审核、版本收据与恢复；时长、标注、字幕使用原函数。
- `media.py` 将原白板路径写入低清预览，或调用原 Remotion CLI；合成调用原 merge 和字幕函数。
- `adapters/voicestudio.py` 增加实际本地协议，原 Gradio/FastAPI TTS 继续调用原函数。
- `project.py` 管理隔离路径、原件保护、原子 JSON、OS 互斥。

`server.py` 原规划提示词和最终合成代码提取为共享函数，原 Web 也调用这些函数；
Skill 导入设置 HEADLESS 禁止旧任务恢复，正常 Web 启动行为保持。Gradio 下载目录新增
可选参数，Skill 显式绑定项目，原 Web 默认行为保持。共享原模块的全局路径绑定用锁串行。

渲染器只增加共享路径/writer 注入及完全遮挡区域帧预算修复。原合并器只适配清单位置、
文件名单引号，以及实际发现的 PyAV 多片重复 PTS；未另写替代合并器。Node 脚本只允许
缓存/bundle、CRF 和并发绑定项目；Skill 单页并发避免本机浏览器大量标签无响应，原 Web 仍默认 50%。
Remotion 保留原规范画布与布局，渲染后仅缩放输出像素。
原 Web 用户数据、密钥、模型及 node_modules 不迁入源码。

Remotion 保持原真实词边界 → 原短语 → 原 PPT 规划归一 → 原 deck 时间轴 → 原 props →
原 render.mjs/React 构图链。用户要求先审叙事分镜、后准备配音，因此初始分镜可用
`--narrative-only`；配音后 `deck request/adapt` 完成原 PPT 布局规划，必须保持已批准的
页数与每页口播，否则重新审核分镜。无词边界时明确停止，不以估计替代原严格对齐。

审核仍由 Agent 对用户实际确认负责，CLI 只核验版本/阶段，无法验证对话说话人身份。
所有基准均标记合成批准；真实成片仍需用户视觉与听觉验收。无自动提交、推送或发布。
