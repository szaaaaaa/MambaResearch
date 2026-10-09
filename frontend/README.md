# MambaResearch 前端

在仓库根运行 `npm ci --prefix frontend`、`npm run build --prefix frontend`。
随后在 Codex App 调用 `$mambaresearch` 打开 MCP App 工作台。

模型执行与论文检索由 Codex 原生能力提供，前端不配置或内联模型 API 密钥。
`npm run dev --prefix frontend` 仅用于开发；普通浏览器不具备 Codex 宿主桥。

验证：`npm test --prefix frontend`、`npm run lint --prefix frontend`。
