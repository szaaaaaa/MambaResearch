# MambaResearch UI — 接入指南

把这三个文件搬进你的 `ResearchAgent/frontend` 项目即可。

## 文件清单
- `colors_and_type.css` — 设计 token（紫金 + 暖色调 + 字体）
- `v3-components.jsx` — Sidebar / Chat / Bubble 组件源码（React inline JSX）
- `v3-style.css` — 所有 `.rb-*` 样式

## 三步接入

### 1. 放置文件
```
ResearchAgent/frontend/src/
├── styles/
│   ├── tokens.css        ← 这里放 colors_and_type.css 的内容
│   └── chat.css          ← 这里放 v3-style.css 的内容
└── components/v2/
    └── chat-components.tsx  ← v3-components.jsx 改写成 .tsx
```

### 2. 引入样式
在 `src/main.tsx` 顶部按顺序：
```tsx
import './styles/tokens.css';
import './styles/chat.css';
import './index.css';
```

给 `<body>` 或根 `<div>` 加 `className="ds-scope"`，token 才会生效。

### 3. .jsx → .tsx 转换要点
- `const { useState } = React` → `import { useState } from 'react'`
- `Object.assign(window, { ... })` → `export { ... }`
- 给 props 加 TypeScript 类型
- 手画 SVG 可以替换成 `lucide-react`（你 package.json 已经有）

## 怎么接你的 store

`<Chat>` 组件里的 `send()` 函数：把里面的 `setHistory` / `setStreaming` 改成调你 `store.tsx` 的 action 即可。UI 完全不用动。

## 字体
`colors_and_type.css` 引用了 Google Fonts (Fraunces / Inter / JetBrains Mono)。如果项目要离线运行，把字体下载到 `public/fonts/` 并修改 `@font-face`。
