# Harvest Community 技术报告

> v0.4.0 · 集成化首次启动向导

## 1. 系统目标

Harvest Community 保留原有的本地优先、故障恢复、结构化输出和人工确认边界，同时把单用户固定六主线改为可复用的用户建模流程。

个性化被拆成两部分：所有人共享“事实、变化、进展、下一步、表达边界”等分析维度；每个人拥有经过确认的 3～7 条长期主线。这样既能维持 JSON Schema 和历史数据的稳定性，也不会强迫不同身份的用户采用同一分类。

## 2. 核心数据流

```text
API 最小连通测试
          │
          ▼
引导式画像问卷 ──► OnboardingProposal（画像 + 个人问题集）
          │
          ▼
真实临时日志测试 ──► 分类反馈 ──► 最多三轮差异确认与复测
          │
          ▼
 UserProfile v1（测试数据全部删除）
          │
          ├──► 下次运行开始正式日报 / 动态主线周报
          │
          └──► 第五份日报校准 ──► UserProfile v2
```

画像版本不可变地保存在 `profile/history`，当前版本另存为 `profile/current.json`。恢复历史内容会创建新版本，避免覆盖审计历史。

## 3. 模型与验证边界

- `ProfileContent` 固定约束阶段、目的、主线、关注信号、暂定观察、表达偏好、行动偏好和解释边界。
- `ThemeDefinition` 使用稳定 ID，数量限制为 3～7；标题和 ID 不允许重复。
- `DailyHarvest.sections` 与 `WeeklyReview.sections` 取代固定字段。
- Provider 完成 Pydantic 校验后，Service 再验证主线 ID、标题和顺序必须与当前画像完全一致。
- 解释边界由程序强制补入，不依赖模型自觉生成。
- 暂定观察必须附证据，置信度只能为 low 或 medium。

旧版 schema v2 日报和周报通过 Pydantic 的输入迁移器映射为 schema v3 动态 sections；旧 Markdown 画像只能由用户显式导入。

## 4. 恢复与隐私

日报和 onboarding 均在每题后原子写入 pending。向导记录当前步骤、画像与问题草案、临时测试报告和脱敏网络追踪，模型或终端失败后无需重做已完成步骤。

最终确认后删除原始问卷、测试答案、测试报告和网络追踪，不创建正式日报。第五份日报前只临时保存自然语言修订意见，校准完成后清除。模型请求设置 `store=false`，但请求内容仍会发送给用户选择的模型供应商。

## 5. 跨平台层

- 配置目录由 `platformdirs` 解析。
- API Key 通过 `keyring` 接入系统凭据库；Linux 后端使用 Secret Service。
- Reminder 模块按平台生成 systemd、launchd 或 Task Scheduler 配置，统一调用无模型副作用的 `harvest notify`。
- PyInstaller spec 生成单文件 CLI；GitHub Actions 在 Linux、Windows、macOS Intel 和 Apple Silicon 上分别测试和构建。

## 6. 测试重点

自动测试覆盖严格 Schema、动态渲染、旧数据迁移、画像版本、差异计算、主线匹配、pending 生命周期、完整 onboarding、第五份日报触发、修订信息清理、跨平台提醒定义、Provider 错误和密钥脱敏。
