# Harvest Community 用户指南

## 1. 启动

clone 仓库后，Linux/macOS 运行 `./run.sh`，Windows PowerShell 运行 `.\run.ps1`。第一次会自动建立 `.venv` 并安装依赖。之后不带参数启动：未完成首次调试时继续向导，已完成时开始今天的正式复盘。

第一步只选择 AI 服务商和配置 API Key，并发送一次最小真实请求检查 Key、网络和结构化响应。Key 写入系统凭据库；凭据库不可用时请使用 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` 环境变量，不会降级保存明文文件。

桌面提醒按平台安装为用户级任务：Linux 使用 systemd user timer，macOS 使用 launchd，Windows 使用 Task Scheduler。提醒只调用 `harvest notify`，不会读取记录或请求模型。

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

每日使用 5～7 个已确认的个人问题，至少包含基本生活状态和明日衔接；旧画像继续使用兼容的固定六题。日报预览必须由用户确认，模型失败时原始回答保留在 `pending`。

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

周报沿当前画像的主线总结已有记录；缺失日期只表示未知。AI 提出的项目记忆更新必须由用户确认。

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

运行 `harvest doctor` 检查配置、数据目录、画像、凭据和提醒；加 `--api-test` 会发送一次最小真实请求。

运行 `harvest settings` 可在首次调试之后修改服务商、数据目录和桌面提醒。
