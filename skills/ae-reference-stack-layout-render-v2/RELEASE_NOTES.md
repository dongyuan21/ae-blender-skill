# Release Notes — v2.0.0

本版本是面向 Codex 5.6 SOL（推理深度 extra-high）的状态化 AE 牌堆迁移 Skill。其他模型没有验证。

## 关键变化

- 使用不可变 Receipt DAG 与 CAS 状态提交，避免旧 Worker 覆盖新状态。
- 将源 AE 玩法事实、参考图可见几何、隐藏容量、牌到 Slot 的分配拆成四个互不越权的权威 Artifact。
- Assignment 每行只允许 `tileId` 与 `slotId`，禁止夹带 `zOrder`、活动区间、点击时间或坐标。
- 新增确定性容量协调、约束分配求解、点击可达性模拟、遮挡顺序检查和 Property Plan 构造。
- 将 GPT 角色拆成提案者与独立复核者；复核不能沿用提案上下文自我批准。
- AE 写入仅作用于隔离副本，执行 expected-old 检查、依赖锁、fresh reopen/readback 与原始 AEP Hash 防护。
- QA 使用 typed issue code 回退到最早的权威节点，禁止在 QA 阶段直接修 AEP。
- 随包提供 40 个可见 Anchor、57 个物理 Slot、17 个隐藏 Slot 的 Golden Fixture。

## 离线验证

发布前已通过：

- 15 项 Python 回归测试；
- 全部 JSON 解析；
- 7 组 JSON Schema 验证；
- Python `compileall`；
- 3 个 JSX 文件的静态约束与 Node 语法检查；
- Golden Fixture：57/57 一一分配、零 blocked click、零 occlusion-order violation。

## 尚未执行的验证

当前构建环境没有目标 Windows After Effects 宿主，因此没有实际执行 AEP 打开、修改、保存、fresh reopen 和完整渲染。对应脚本、事务合同和离线测试已完成，但第一次用于真实项目时仍需在目标 AE 版本与依赖齐全的 Windows 主机上做 smoke test。
