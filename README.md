# Harvest Community

Harvest 是一个本地优先、可持续校准的 AI 个人复盘 CLI。
它通过个性化问题帮助你观察自己的状态与变化，并把当天经历整理成明天可以继续的行动线索。

> [下载 Harvest 最新独立版](https://github.com/MoonMing-ely/harvest-community/releases/latest)
>
> 支持 Windows、macOS 和 Linux。独立版已包含 Python，解压后即可运行。

## 为什么使用 Harvest

- **问题来自你自己**：首次使用时建立个人画像、长期主线和每日问题，不要求所有人套用同一份复盘模板。
- **记录指向下一步**：AI 将回答整理为结构化日报，保留进展、变化、阻碍和后续行动；内容不准确时可以随时修订。
- **跨天形成连续观察**：项目记忆连接最近进展，Weekly Review 沿个人主线总结趋势，而不是只统计完成数量。
- **数据与注意力都由你控制**：记录保存在本地，提醒使用系统通知中心；不追踪屏幕，不用弹窗打断当前工作。

## 适合谁

Harvest 适合同时推进学习、个人项目、创作或生活调整，希望通过持续记录理解自己，并保留清晰下一步的人。

它尤其适合不喜欢打卡、绩效评分和固定复盘模板，但愿意每天花几分钟如实回答问题的用户。使用 AI 生成功能需要自己的 DeepSeek 或 OpenAI API Key。

如果你需要自动屏幕追踪、团队任务协作、完全离线的本地模型，或希望工具替你做决定，Harvest 目前并不适合这些需求。

## 三步完成一次复盘

1. 运行 Harvest。首次启动会引导你配置模型，并建立个人画像和问题集。

   ```bash
   harvest
   ```

2. 回答 5～7 个个性化问题。每答完一题都会保存进度，中断后可以继续。

3. Harvest 自动生成并保存日报。如果内容需要补充或纠正，直接提交修改意见：

   ```bash
   harvest revise 2026-09-01 --correction "这里还没有完成，只是确认了方案"
   ```

日报以 JSON 和 Markdown 保存。积累多日记录后，可以生成 Weekly Review，观察长期主线中的变化、卡点与下一步。

## 安装

普通用户请在 [Releases](https://github.com/MoonMing-ely/harvest-community/releases/latest) 下载对应压缩包：

- Windows 64 位：`harvest-windows-x86_64.zip`
- macOS Apple 芯片：`harvest-macos-arm64.tar.gz`
- macOS Intel：`harvest-macos-x86_64.tar.gz`
- Linux 64 位：`harvest-linux-x86_64.tar.gz`

解压后运行其中唯一的可执行文件。Windows 可以在解压目录运行：

```powershell
.\harvest-windows-x86_64.exe
```

Linux 或 macOS 使用对应文件名，例如：

```bash
chmod +x harvest-linux-x86_64
./harvest-linux-x86_64
```

macOS 独立版尚未签名。首次运行若被 Gatekeeper 阻止，请在“系统设置 → 隐私与安全性”中确认打开。

API Key 保存到 Windows Credential Manager、macOS Keychain 或 Linux Secret Service。系统凭据库不可用时，可以使用 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` 环境变量。

## 五个核心命令

| 目的 | 命令 |
|---|---|
| 开始今天的复盘 | `harvest` |
| 继续未完成的回答 | `harvest resume 2026-09-01` |
| 修订已生成的日报 | `harvest revise 2026-09-01` |
| 生成周度回顾 | `harvest weekly` |
| 检查配置与运行状态 | `harvest doctor` |

完整命令和使用说明见 [用户指南](docs/user-guide.md)。

## 隐私边界

- 日报、周报、画像和项目记忆保存在你选择的本地目录。
- 只有生成当前内容所需的回答、画像和精简项目上下文会发送给所选模型供应商。
- API Key 优先保存在操作系统凭据库，不写入日志或报告。
- Harvest 不监控屏幕、窗口或键盘活动；桌面提醒只检查对应日期的日报是否存在，不调用模型。

更完整的数据生命周期和安全设计见 [技术报告](docs/technical-report.md)。

## 从源码运行与开发

源码方式需要 Python 3.11+。克隆仓库后，Linux 或 macOS 运行 `./run.sh`，Windows PowerShell 运行 `.\run.ps1`。

脚本会根据带哈希的依赖锁创建项目内 `.venv`，不会修改 Harvest 数据目录。也可以手动建立开发环境：

```bash
python -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements/dev.lock
PYTHONPATH=src .venv/bin/python -m pytest
```

构建当前平台的独立文件：

```bash
.venv/bin/pyinstaller --clean --noconfirm harvest.spec
```

项目的个性化流程、数据结构、故障恢复和跨平台实现详见 [技术报告](docs/technical-report.md)。
