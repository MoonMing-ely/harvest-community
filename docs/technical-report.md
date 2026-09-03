# Harvest Community 技术报告

> v0.5.1 · 终端与供应链安全加固

## 1. 系统目标

Harvest Community 保留原有的本地优先、故障恢复、结构化输出和人工确认边界，同时把单用户固定六主线改为可复用的用户建模流程。

个性化被拆成两部分：所有人共享“事实、变化、进展、下一步、表达边界”等分析维度；每个人拥有经过确认的 3～7 条长期主线。这样既能维持 JSON Schema 和历史数据的稳定性，也不会强迫不同身份的用户采用同一分类。

## 2. 核心数据流

```text
API 最小连通测试
          │
          ▼
引导式画像问卷 + 本地逐题检查 ──► OnboardingProposal（画像 + 个人问题集）
          │
          ▼
真实临时日志测试 ──► 分类反馈 ──► 不限轮次的差异确认、复测或完成
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

日报和 onboarding 均在每题后原子写入 pending。向导记录当前步骤、画像与问题草案、临时测试报告和不含请求正文的网络摘要，模型或终端失败后无需重做已完成步骤。旧版 pending 中的请求与响应正文会在加载时丢弃，并在下次保存后完成迁移。

最终确认后删除原始问卷、测试答案、测试报告和网络摘要，不创建正式日报。重新建档以当前画像版本为基线，确认前不替换当前画像，也不改写历史日志。第五份日报前只临时保存自然语言修订意见，校准完成后清除。模型请求设置 `store=false`，但请求内容仍会发送给用户选择的模型供应商。原始请求与响应仅可通过 `doctor --api-test --details` 在当前进程中查看，不会持久化；API Key 和 Authorization 始终被排除。

所有用户可见的模型调用由统一状态上下文包裹，终端持续显示动态 dots 和具体任务；退出上下文后无论成功或失败都会停止动画。操作型菜单只接受明确序号并标记推荐项，个性化选择则允许编号、多选和自由文字且不施加推荐。

所有用户输入、模型响应、旧记录和可选外部状态在结构化边界递归净化，只保留可打印字符与规范换行。Rich Console 默认关闭 markup；程序样式使用显式 `Text`，Markdown 预览关闭 hyperlinks。校准状态记录终端安全迁移版本，升级后原子清理既有日报和周报 Markdown，不改写外部状态文件。配置字符串通过标准转义写入 TOML，API Key 与提醒参数在进入凭据库、HTTP Header 或系统任务定义前再次校验；格式校验错误不回显模型原文。

Prompt 将指令与 JSON 数据分离，并明确把 JSON 内字符串视为不可信内容；严格 Schema 限制模型输出形状。项目记忆建议仍需人工确认，且默认选择为不应用。语义提示注入无法被完全消除，但它不能直接执行命令或绕过终端净化。

## 5. 跨平台层

- 配置目录由 `platformdirs` 解析。
- API Key 通过 `keyring` 接入系统凭据库；Linux 后端使用 Secret Service。
- Reminder 模块按平台生成 systemd、launchd 或 Task Scheduler 配置，统一调用无模型副作用的 `harvest notify`。
- PyInstaller spec 把 Python 解释器和依赖一起封装为单文件 CLI；GitHub Actions 在 Linux、Windows、macOS Intel 和 Apple Silicon 上分别测试和构建，再生成保留 Unix 执行权限的 `.tar.gz` 或 Windows `.zip`。普通用户无需安装 Python。运行与开发依赖分别由跨平台、带哈希的锁文件固定；工作流 Action 固定到完整提交 SHA，构建默认只有只读权限，发布 job 才获得 `contents: write`。

## 6. 测试重点

自动测试覆盖严格 Schema、动态渲染、旧数据迁移、画像版本、差异计算、主线匹配、pending 生命周期、完整 onboarding、不限轮次修改、回答纠错、重新建档、AI 等待状态、第五份日报触发、跨平台提醒定义、Provider 错误、密钥脱敏、配置与系统任务注入、终端控制字符、Rich markup、旧 Markdown 清理、哈希锁和 CI SHA 固定。
