# Harvest Community 用户指南

## 1. Setup

运行 `harvest setup` 选择 Provider、数据目录和提醒时间。每个人使用自己的 API Key；程序优先读取环境变量，其次读取系统凭据库。

桌面提醒按平台安装为用户级任务：Linux 使用 systemd user timer，macOS 使用 launchd，Windows 使用 Task Scheduler。提醒只调用 `harvest notify`，不会读取记录或请求模型。

## 2. 第一次建立画像

运行：

```bash
harvest onboard
```

流程依次询问当前阶段、复盘目的、长期事项、进展信号、工作节奏、表达偏好、行动建议偏好和一天真实情况。每答完一题立即保存，异常退出后再次运行同一命令即可继续。

AI 会提出 3～7 条主线并生成日报样例。预览时：

- Enter：接受画像和首份日报。
- 输入自然语言：提出画像反馈；AI 显示变更和新画像，确认后重新生成样例。
- `q`：暂停并保留进度。

首次阶段最多修改三轮。之后仍可运行 `harvest profile recalibrate`。

## 3. 日报与恢复

```bash
harvest daily
harvest daily --date 2026-09-01
harvest resume 2026-09-01
harvest revise 2026-09-01 --correction "这里不是完成，只是确认了方案"
```

六个固定问题用于帮助回忆，用户不需要自行分类；模型按照画像中的个人主线整理。日报预览必须由用户确认，模型失败时原始回答保留在 `pending`。

第五个不同日期的正式日报保存后，程序提供三种选择：立即微调、稍后再问、永不自动询问。立即微调会参考五份正式日报和保存期间的修改意见；修改确认后从下一份日报生效，不改写第五份日报。

## 4. 画像管理

```bash
harvest profile
harvest profile recalibrate
harvest profile history
harvest profile restore 2
harvest profile import-legacy ~/.config/harvest/report-profile.md
```

恢复历史版本不会覆盖历史文件，而是创建一个新的当前版本。旧版 Markdown 画像只会通过显式命令读取，原文件保持不变。

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
