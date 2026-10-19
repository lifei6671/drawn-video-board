# macOS DMG

使用 `build-dmg.sh` 构建 Apple Silicon 版本的安装包：

```bash
./packaging/macos/build-dmg.sh
```

构建前需要准备：

- macOS、`clang`、`hdiutil`、`rsync` 和 Node.js；
- 已安装依赖的 `web/node_modules` 与 `video_renderer/node_modules`；
- 已安装项目依赖的 `.venv`；
- `.venv` 中的 PyInstaller，可用 `uv pip install --python .venv/bin/python 'pyinstaller>=6.16,<7'` 安装。

产物位于 `dist/CSBoard-0.1.0-arm64.dmg`。应用数据和任务历史保存在用户目录下的 `~/Library/Application Support/CS Board`，不会写入只读的应用包。

当前产物面向 Apple Silicon，未进行 Apple Developer 签名或公证；从网络下载后首次打开时可能需要在 Finder 中右键选择“打开”。
