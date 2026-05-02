# 复测清单 — CLI PTY Pivot 阻断修复后回归

**日期**: 2026-05-02
**对应 plan**: `docs/plans/2026-05-01-cli-pty-pivot.md`
**修复 commit**: `5b4a1ac` — fix(workbench): cure [reconnecting...] loop + invisible PTY errors
**状态**: 等待 ziang 手动复测

## 背景

上一轮 manual test ziang 报告：B2/B3/B5/B6/B7/C1 全部因 Claude PTY 重启卡 `[reconnecting...]` 而 block。本轮已落三处修复，**未复现原 bug，仅瞄准诊断**——以下复测用例就是用来验证修复是否真覆盖了那个症状。

## 修复瞄准的诊断（仅供理解，不必逐条验证）

| # | Bug | 修法 |
|---|-----|------|
| 1 | 旧 WS 的 `onclose` 在 cleanup 后异步触发，读到刚被新 effect 重置的 `closedByEffectRef=false`，幽灵重连 → 两个 `PtyProcess` 抢 ConPTY | `TerminalPane.tsx` cleanup 把 4 个 ws handler 都置 null 再 close |
| 2 | 切项目时 `claudeConversationId` 清空 → `ensureConversation` 异步重建 → effect 跑两次 → TerminalPane 双挂载 | `WorkbenchTab.tsx` 渲染 `<TerminalPane>` 前 gate 在 `conversationId` 上 |
| 3 | `pushError` 写到 items 列表，Claude 分支没渲染 → fatal 静默 | 新 `claudePtyError` state + 顶部红条 + "重启 PTY" 按钮 |
| 副带 | POST `/api/conversations` 失败会让 Claude tab 永远卡"正在创建对话…" | `NO_MIRROR_SENTINEL='no-mirror'` 兜底，失败也照样挂终端（不写 mirror） |

## 复测前置

- 后端: `python app.py` 起着
- 前端开发: `cd frontend && npm run dev`
- 浏览器开 DevTools，Console + Network → WS 都打开备用
- 至少 2 个 project 可切换

## 复测顺序（简单 → 复杂）

### B7 — PTY 重启路径（最简单，先测）
**操作**:
1. Claude tab 中打开终端，输入 `/exit` 让 CLI 主动退出
2. 顶部应出现红条 + "重启 PTY" 按钮
3. 点"重启 PTY"

**预期**: 秒级出现新的 Claude prompt（无 `[reconnecting...]` 卡住）

**失败时报**: 截图红条文案 + Console 报错 + 是否真的 spawn 了新 PTY（看后端日志）

---

### B2 / B3 — Tab 切换不丢终端
**操作**:
1. Claude tab 发一句话，等回复完
2. 切到 Codex tab（或别的非 chat tab）
3. 切回 Claude tab

**预期**: 终端历史还在，prompt 可继续输入，**不出现** `[reconnecting...]`

**失败时报**: DevTools → Network → 筛选 `ws` → 截图最近一条 WS 的 status + Frames 面板（看有没有 fatal frame、有没有同时挂两个 WS）

---

### B5 / B6 — 切 active project
**操作**:
1. Claude tab 跑一段对话
2. 通过项目切换器切到另一个 project
3. 再切回原 project

**预期**: 每次切换都有新的 PTY 干净启动，不卡 reconnecting

**失败时报**: 同 B2/B3 的 WS 截图

---

### C1 — messages 表 mirror（**注意复测程序修正**）
**关键**: TurnTeer 在 `\r`（用户回车下一条）或 ws 关闭时才切 turn 写库。所以**发完一句 assistant 回复不会立刻出现在 DB**。

**操作**:
1. Claude tab 发 input1 → 等 assistant 回复完
2. 发 input2（**这一步把上一轮 turn flush 到 DB**），或者直接关 PTY（点 Logout / 切 backend）
3. 查 DB:
   ```sql
   sqlite3 ~/.research-agent/conversations.db
   SELECT id, conversation_id, role, substr(content,1,80) FROM messages
     WHERE conversation_id='<刚才那个>' ORDER BY created_at;
   ```

**预期**: 至少能看到 input1 和 assistant 第一轮回复的两条

**失败时报**: DB 查询输出 + 后端日志里 `output_parser` / `pty_bridge` 相关行

## 任何 case 仍卡 `[reconnecting...]` 时的统一抓帧

DevTools → Network → 筛选 `ws` → 截图：
- WS 的 status（101 成功 / 4xx 5xx 失败）
- Frames 面板最后 5-10 条（重点看 `fatal` 控制帧、PTY exit、resize）
- Console 里红字 / yellow warning

发我截图，看实际行为再二次定位。

## 复测通过后的状态推进

Plan 中以下 task 当前 `[PENDING-VERIFY]`，复测全过后 ziang 确认 → mark `[DONE]`：

- Task 3
- Task 4
- Task 5
- Task 6b
- Task 7
