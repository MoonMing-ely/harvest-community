# Harvest Community 用户指南

## 1. 启动

普通用户从 [GitHub Releases 最新版](https://github.com/MoonMing-ely/harvest-community/releases/latest) 下载与系统匹配的压缩包，解压后直接运行其中的 `harvest-*` 程序。独立版包含 Python 运行时，无需安装 Python 或依赖。Windows 使用 `.zip`；Linux 和 macOS 使用 `.tar.gz`，解压会保留执行权限。macOS 版本尚未签名，首次启动若被系统拦截，需要在“系统设置 → 隐私与安全性”中确认打开。

从源码开发时，clone 仓库后在 Linux/macOS 运行 `./run.sh`，Windows PowerShell 运行 `.\run.ps1`。第一次会按仓库内带哈希的锁文件建立 `.venv` 并安装依赖；锁文件更新时脚本会重建这个项目专用环境，但不会修改 Harvest 数据目录。

之后不带参数启动：未完成首次调试时继续向导，已完成时开始今天的正式复盘。

第一步只选择 AI 服务商和配置 API Key，并发送一次最小真实请求检查 Key、网络和结构化响应。Key 写入系统凭据库；凭据库不可用时请使用 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` 环境变量，不会降级保存明文文件。

桌面提醒按平台安装为用户级任务：Linux 使用 systemd user timer 和 Freedesktop 通知，macOS 使用 launchd 和系统通知中心，Windows 使用 Task Scheduler 和 Toast。提醒只调用 `harvest notify`，在本地检查当天日报是否已经存在，不读取正文、不请求模型，也不会弹出抢焦点的对话框。错过设定时间后只在三小时内补提醒。

## 2. 首次调试四步流程

运行：

```bash
harvest
```

第二步通过六组选项和一个高度引导的具体经历，建立 3～7 条个人主线和 5～7 个每日问题。进入选择前，程序会说明以后可用 `harvest profile rebuild` 重新建立画像和筛选问题。画像只总结明确事实和可观察的理解、验证、排错策略；少量倾向必须标记为低或中置信度，不评价人格、智力或能力。

问题以个人体验、自我观察、成长与决策为中心。具体项目和任务只用于帮助回忆事实，最多一个问题主要询问“做了什么”。问卷和测试答案发送前都会显示本地摘要，可按题号返回修改。

第三步会明确告知用户正在测试，并发起真实 API 请求以检查输入、输出、网络和格式。所有问题均可跳过；全部留空时只能报告信息不足。测试日志不是正式日报。

第四步可按画像、每日问题、日志内容和表达格式提出改进，不限制修改轮数。每份修改方案都明确提供应用并重测、继续修改、立即完成或放弃方案等去向；只有应用的方案才计入版本。第一次修改后重新回答全部测试题，之后只询问新 ID 的问题并保留稳定 ID 的答案。

所有 AI 请求期间都会显示动态等待提示和当前任务。等待通常需要几秒到几十秒，可按 `Ctrl+C` 暂停；向导和日报中已经写入 pending 的输入不会丢失。

最终确认只保存画像和问题集，并删除原始向导回答、测试答案、测试日志和追踪信息。不会立刻生成正式日报。输入 `q` 可暂停，重新运行 `harvest` 会从保存步骤继续。

## 3. 日报与恢复

```bash
harvest daily
harvest daily --date 2026-09-01
harvest resume 2026-09-01
harvest revise 2026-09-01 --correction "这里不是完成，只是确认了方案"
```

每日使用 5～7 个已确认的个人问题，至少包含基本生活状态和明日衔接；旧画像继续使用兼容的固定六题。日报生成成功后会自动保存，并提示使用 `harvest revise YYYY-MM-DD` 修改；模型失败时原始回答保留在 `pending`。

第五个不同日期的正式日报保存后，程序提供三种选择：立即微调、稍后再问、永不自动询问。立即微调会参考五份正式日报和保存期间的修改意见；修改确认后从下一份日报生效，不改写第五份日报。

## 4. 画像管理

```bash
harvest profile
harvest profile recalibrate
harvest profile rebuild
harvest profile history
harvest profile restore 2
harvest profile import-legacy ~/.config/harvest/report-profile.md
```

恢复历史版本不会覆盖历史文件，而是创建一个新的当前版本。旧版 Markdown 画像只会通过显式命令读取，原文件保持不变。

`harvest profile rebuild` 可选择基于当前画像调整（推荐），或从头回答全部问卷。重建完成前旧画像持续生效，历史日志不会被删除或改写。

## 5. 周报和项目记忆

```bash
harvest weekly
harvest weekly --week 2026-W36
harvest project add "项目名称" --next-step "下一步"
harvest project list --all
harvest project pause "项目名称"
harvest project activate "项目名称"
harvest project complete "项目名称"
```

周报沿当前画像的主线总结已有记录；缺失日期只表示未知。AI 提出的项目记忆更新会自动应用原有名称和状态规则校验，并显示实际更新或跳过结果。

## 6. 数据与故障检查

数据目录包含：

```text
daily/YYYY/MM/*.json|md
weekly/YYYY/*.json|md
pending/*.json
memory/projects.json
profile/current.json
profile/history/v*.json
profile/calibration.json
```

运行 `harvest doctor` 检查配置、数据目录、画像、凭据和提醒；加 `--api-test` 会发送一次最小真实请求，并只显示连接、格式、耗时和 Token 摘要。

只有排错时才使用 `harvest doctor --api-test --details` 查看本次请求与响应。详情不会写入数据目录，但可能包含个人输入和模型结果，请勿直接公开分享。API Key 和 Authorization 始终不会显示。

Harvest 会在数据进入结构化模型、保存文件和输出终端时清理不可打印控制字符。配置、API Key 和提醒参数也会在写入配置、HTTP 请求或系统任务前校验。旧版生成的日报与周报 Markdown 会在升级后首次运行时自动完成一次安全清理；用户主动指定的外部状态文件只读，不会被改写。

运行 `harvest settings` 可在首次调试之后修改服务商、数据目录和桌面提醒。
