# Harvest Community

Harvest 是一个本地优先、可校准的个人复盘 CLI。它以人的体验、选择、成长和自我观察为中心，具体项目只是帮助回忆的事实载体。用户 clone 后通过中文向导完成 API 配置、用户画像、个人问题集和真实联网测试，然后即可开始日常复盘。

> [⬇️ 一键下载 Harvest 最新版（ZIP）](https://github.com/MoonMing-ely/harvest-community/archive/refs/heads/main.zip)
>
> 下载后解压。Linux/macOS 运行 `./run.sh`，Windows PowerShell 运行 `.\run.ps1`；需要 Python 3.11 或更高版本。

## 个性化流程

1. 配置 AI 服务商与 API Key，并用最小真实请求检查网络和 JSON 格式。
2. 通过六组选项和一个具体经历，生成可确认的画像与 5～7 个个人问题。
3. 运行一次明确标记的真实测试；测试日志、答案和网络追踪不会成为正式日报。
4. 按“画像 / 问题 / 日志内容 / 格式”反复修改、复测或立即完成；每个动作都有明确说明。
5. 完成后直接运行 `harvest`，才会开始当天的正式日报。

AI 只总结可观察偏好。工作风格只能作为有依据、低或中置信度的“暂定观察”；不得诊断心理、评价人格或能力。

调用 AI 时终端会显示动态等待提示。画像和问题不是一次性设置：以后可运行 `harvest profile rebuild` 重走完整流程，也可用 `harvest revise YYYY-MM-DD` 修改已保存日志。

## 安装与首次使用

可以点击上方链接下载 ZIP，也可以执行 `git clone https://github.com/MoonMing-ely/harvest-community.git`。Linux 或 macOS 运行 `./run.sh`，Windows PowerShell 运行 `.\run.ps1`。脚本会创建项目内虚拟环境、安装依赖并打开 Harvest；以后仍使用同一命令。

朋友使用自己的 DeepSeek 或 OpenAI API Key。Key 保存到 Windows Credential Manager、macOS Keychain 或 Linux Secret Service；凭据库不可用时使用 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` 环境变量，程序不会为新用户降级写入明文 Key 文件。

## 常用命令

```bash
harvest daily
harvest resume 2026-09-01
harvest revise 2026-09-01
harvest weekly
harvest show 2026-09-01

harvest profile
harvest profile recalibrate
harvest profile rebuild
harvest profile history
harvest profile restore 1

harvest doctor
harvest doctor --api-test
harvest settings
```

完整说明见 [用户指南](docs/user-guide.md)，架构与数据流见 [技术报告](docs/technical-report.md)。

## 从源码开发

需要 Python 3.11+：

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/pytest
```

Windows 激活后的 Python 路径为 `.venv\Scripts\python.exe`。构建当前平台的独立文件：

```bash
.venv/bin/pyinstaller --clean --noconfirm harvest.spec
```

打 `v*` 标签后，GitHub Actions 会测试并构建四个平台产物及 SHA-256 校验文件。

## 隐私边界

- 正式 JSON、Markdown、项目记忆、画像和校准状态保存在用户选择的数据目录。
- 日报接受后删除原始回答；onboarding 完成后删除原始问卷和首日回答。
- 生成日报时发送当前回答、结构化画像和精简项目列表给所选模型供应商。
- 第五份微调会发送五份正式报告和此前的日报修改意见，并在界面中提前说明。
- 微调完成后删除原始修改意见，只保留画像版本。
- 可选的外部状态文件默认关闭，不会自动读取个人目录。
