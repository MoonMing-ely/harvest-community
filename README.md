# Harvest Community

Harvest 是一个本地优先、可校准的个人复盘 CLI。它不会要求所有人使用同一套生活分类，而是通过固定问卷、真实日报样例和用户确认，建立 3～7 条个人长期主线。

## 个性化流程

1. `harvest onboard` 用七个画像问题和一天真实记录建立第一版画像。
2. 程序展示画像与日报样例；用户可用自然语言修改，最多三轮。
3. 确认后的样例成为第一份正式日报。
4. 累计五份不同日期的日报后，程序结合正式报告和修订意见询问是否微调。
5. 所有画像修改先显示差异，确认后才保存为新版本。

AI 只总结可观察偏好。工作风格只能作为有依据、低或中置信度的“暂定观察”；不得诊断心理、评价人格或能力。

## 安装与首次使用

发布页提供以下独立可执行文件：

- Linux x86-64
- Windows x86-64
- macOS Intel
- macOS Apple Silicon

首轮测试版本没有代码签名或 macOS notarization。下载后先核对同名 `.sha256` 文件，再按系统提示允许执行。

```bash
harvest setup
harvest onboard
harvest daily
```

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
harvest profile history
harvest profile restore 1

harvest doctor
harvest doctor --api-test
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
