# 本地归档（不进入 GitHub）

原始压缩包和全分辨率素材只保存在本机，**不要** `git add` 或 push 到 GitHub。

## 目录约定

把 zip 和解压后的原始媒体放到被忽略的 `notes/archives/`：

```text
notes/archives/
  素材内容.zip
  ae-reference-stack-layout-render-v2.0.0.zip
  ae-reference-stack-layout-render/    # 展示用原始 mp4 / png
```

本地未打包工作目录 `raw/` 也被 `.gitignore` 忽略。

`notes/archives/`、`raw/` 与仓库根目录的 `*.zip` 已写入 `.gitignore`。GitHub 仓库里只保留：

- `skills/` 中的 Skill 正文与脚本
- `docs/assets/` 中压缩后的展示媒体（约 480 宽、15 fps 的 MP4 与短 GIF）
- 本说明文件

## 当前归档

| 本地文件 | 用途 |
| --- | --- |
| `ae-reference-stack-layout-render-v2.0.0.zip` | 当前 Skill 打包副本 |
| `素材内容.zip` / `ae-reference-stack-layout-render/` | 改造前/后视频与过程图原件 |

展示页使用的压缩文件在 [`docs/assets/ae-reference-stack-layout-render/`](../docs/assets/ae-reference-stack-layout-render/)。重新压缩可运行 [`docs/scripts/compress-showcase.sh`](../docs/scripts/compress-showcase.sh)。
