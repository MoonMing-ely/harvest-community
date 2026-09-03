# Harvest Community

Harvest 是一个本地优先、可校准的个人复盘 CLI。它以人的体验、选择、成长和自我观察为中心，具体项目只是帮助回忆的事实载体。用户 clone 后通过中文向导完成 API 配置、用户画像、个人问题集和真实联网测试，然后即可开始日常复盘。

> [⬇️ 下载 Harvest 最新独立版](https://github.com/MoonMing-ely/harvest-community/releases/latest)
>
> 按操作系统下载对应压缩包，解压后直接运行；独立版已经包含 Python，不需要另行安装运行环境。

## 个性化流程

1. 配置 AI 服务商与 API Key，并用最小真实请求检查网络和 JSON 格式。
2. 通过六组选项和一个具体经历，生成可确认的画像与 5～7 个个人问题。
3. 运行一次明确标记的真实测试；测试日志、答案和网络追踪不会成为正式日报。
4. 按“画像 / 问题 / 日志内容 / 格式”反复修改、复测或立即完成；每个动作都有明确说明。
5. 完成后直接运行 `harvest`，才会开始当天的正式日报。

AI 只总结可观察偏好。工作风格只能作为有依据、低或中置信度的“暂定观察”；不得诊断心理、评价人格或能力。

调用 AI 时终端会显示动态等待提示。画像和问题不是一次性设置：以后可运行 `harvest profile rebuild` 重走完整流程，也可用 `harvest revise YYYY-MM-DD` 修改已保存日志。

## 安装与首次使用

普通用户请从 [Releases 最新版](https://github.com/MoonMing-ely/harvest-community/releases/latest) 下载对应文件：

- Windows 64 位：`harvest-windows-x86_64.zip`
- macOS Apple 芯片：`harvest-macos-arm64.tar.gz`
- macOS Intel：`harvest-macos-x86_64.tar.gz`
- Linux 64 位：`harvest-linux-x86_64.tar.gz`

解压后在终端运行其中唯一的 `harvest-*` 程序，不需要 Python。Windows 可在解压目录执行 `.\harvest-windows-x86_64.exe`；Linux/macOS 执行 `./harvest-对应平台`。macOS 独立版尚未签名，首次运行若被 Gatekeeper 拦截，需要在“系统设置 → 隐私与安全性”中确认打开。

源码方式只面向开发者：执行 `git clone https://github.com/MoonMing-ely/harvest-community.git` 后，Linux/macOS 运行 `./run.sh`，Windows PowerShell 运行 `.\run.ps1`。源码脚本需要 Python 3.11+，会按带哈希的依赖锁创建项目内虚拟环境；只有锁文件变化时才会重建 `.venv`，不会影响 Harvest 数据目录。

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
harvest doctor --api-test --details
harvest settings
```

完整说明见 [用户指南](docs/user-guide.md)，架构与数据流见 [技术报告](docs/technical-report.md)。

## 从源码开发

需要 Python 3.11+：

```bash
python -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements/dev.lock
PYTHONPATH=src .venv/bin/python -m pytest
```

Windows 激活后的 Python 路径为 `.venv\Scripts\python.exe`。构建当前平台的独立文件：

```bash
.venv/bin/pyinstaller --clean --noconfirm harvest.spec
```

维护者升级依赖时使用 uv 0.12.9 重新生成跨平台锁文件：

```bash
uv pip compile --universal --generate-hashes pyproject.toml -o requirements/runtime.lock
uv pip compile --universal --generate-hashes --extra dev pyproject.toml -o requirements/dev.lock
```

打 `v*` 标签后，GitHub Actions 会测试并构建四个平台的独立压缩包及 SHA-256 校验文件；压缩包中的程序包含 Python 运行时。

## 隐私边界

- 正式 JSON、Markdown、项目记忆、画像和校准状态保存在用户选择的数据目录。
- 日报接受后删除原始回答；onboarding 完成后删除原始问卷和首日回答。
- 生成日报时发送当前回答、结构化画像和精简项目列表给所选模型供应商。
- 第五份微调会发送五份正式报告和此前的日报修改意见，并在界面中提前说明。
- 微调完成后删除原始修改意见，只保留画像版本。
- 首次引导只持久化网络测试摘要，不保存请求与响应正文。
- `doctor --api-test --details` 仅在当前终端显示排错数据；其中可能含有个人输入，请勿直接公开分享。
- 可选的外部状态文件默认关闭，不会自动读取个人目录。
- 用户输入、模型文本和外部状态中的终端控制字符会被替换；Rich markup 与超链接不会从这些内容中执行。
- AI 提出的项目记忆更新默认不应用，必须明确确认后才会写入。
