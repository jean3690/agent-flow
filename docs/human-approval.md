# 人工审批

工作流执行到 `human_approval` 节点时暂停等待人工判断，适合发布、外发、扣款等敏感动作前的最后一道确认。

## 时序

```
用户执行工作流
  └─ human_approval 节点 → POST /internal/approvals 创建待办
       └─ 每 2s 轮询 /internal/approvals/{id}（SSE 连接保持）
            └─ 审批人在「审批」页通过 / 驳回
                 ├─ 通过：节点输出 approved=true，流程继续
                 ├─ 驳回 + rejectBehavior=fail：节点失败，流程停止
                 └─ 驳回 + rejectBehavior=continue：输出 approved=false，交给下游条件分支
```

## 节点配置

| 字段 | 说明 |
| --- | --- |
| `title` | 待办标题，支持模板变量 |
| `content` | 审批正文；留空自动取直接上游输出，最多 20000 字 |
| `waitSeconds` | 最长等待，30–600 秒，默认 120 |
| `rejectBehavior` | `fail` 停止流程；`continue` 继续但 `approved=false` |
| `autoApprove` | 演示开关，开启后不创建待办直接通过 |

输出：`approved` / `approvalId` / `status` / `comment` / `decidedBy` / `auto`。

## 超时与执行级超时

- 节点创建待办时把 `expiresInSeconds` 设为 `waitSeconds`，到点后任务变 `EXPIRED`。
- 平台服务在提交执行时会扫描 `human_approval` 节点，把整次执行的 `options.timeoutMs` 至少提升到 `waitSeconds + 30s`，避免图级超时先于审批到期。
- 超过等待时间节点失败，需要重新发起执行；待办不会自动重放。
- 长时间挂起会占用一个执行并发槽；默认建议控制在 2 分钟内，生产部署需同步检查反向代理的 SSE 读超时。

## 状态与权限

| 状态 | 含义 |
| --- | --- |
| `PENDING` | 等待处理 |
| `APPROVED` | 已通过 |
| `REJECTED` | 已驳回 |
| `EXPIRED` | 超过等待时间，读取时惰性标记 |

- 待办归属为触发执行的用户；普通用户只能看到并处理自己的待办，管理员可处理全部。
- 「审批」页默认展示待处理，15 秒自动刷新，也可手动刷新。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/approvals?status=PENDING` | 审批列表，普通用户只看自己的 |
| POST | `/api/approvals/{id}/decide` | `{ approved, comment }`；驳回建议填写原因 |
| POST | `/internal/approvals` | ai-service 创建待办（`X-Internal-Token`） |
| GET | `/internal/approvals/{id}` | ai-service 轮询状态（`X-Internal-Token`） |

## Mock 行为

- `AI_MOCK_MODE=always` 时审批节点自动通过，不创建待办，便于 e2e 与离线演示。
- 单独开启节点 `autoApprove` 也会自动通过，但不受全局 mock 模式影响。

## 边界

- 暂未接入邮件 / IM 通知，审批人需要主动打开「审批」页。
- 审批正文截断到 20000 字，超长内容建议先落文件或知识库再在正文里引用。
- 当前是「阻塞式等待」而不是 LangGraph 中断恢复；服务重启会中断等待中的执行，需要重新发起。
- 高并发场景下不建议大量长等待审批，应改为异步任务 + 回调或独立审批系统。
