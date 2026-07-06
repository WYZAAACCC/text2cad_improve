# Text-to-CAD 智能建模平台

基于自然语言描述生成 3D CAD 模型的 Web 应用前端原型。用户在对话框中输入文字描述，系统解析后生成对应的 3D 几何体并渲染到视图中，同时支持数据集管理（保存、浏览、复用历史设计）。

## 环境依赖

### 运行环境

- **Node.js** >= 18
- **npm** >= 9（或 pnpm / yarn）

### 技术栈

| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| 构建工具 | Vite | ^8.0 | 开发服务器与项目构建 |
| 语言 | TypeScript | ~6.0 | 类型安全 |
| UI 框架 | React | 18 | 组件化界面 |
| 3D 渲染 | Three.js | ^0.184 | 底层 WebGL 渲染 |
| 3D React 绑定 | @react-three/fiber | ^9.6 | React 声明式 Three.js |
| 3D 辅助库 | @react-three/drei | ^10.7 | 轨道控制、网格、相机等 |
| 状态管理 | Zustand | ^5.0 | 全局状态（对话、模型、数据集） |
| 样式 | TailwindCSS | ^4.3 | 暗色主题样式 |
| HTTP 客户端 | Axios | ^1.17 | API 请求结构（当前为 mock） |
| 异步状态 | @tanstack/react-query | ^5.101 | 异步数据管理 |
| UI 原子组件 | Radix UI | ^1.1 | Tabs、Dialog、Slider、Collapsible |
| 图标 | Lucide React | ^1.17 | 界面图标 |

### 开发依赖

- `@vitejs/plugin-react` — Vite 的 React 插件
- `@tailwindcss/vite` — TailwindCSS 的 Vite 插件
- `@types/three` — Three.js 类型声明
- `@types/react-dom` — React DOM 类型声明

## 快速开始

```bash
# 安装依赖
npm install

# 启动开发服务器（默认 http://localhost:5173）
npm run dev

# 类型检查 + 生产构建
npm run build

# 预览生产构建产物
npm run preview
```

## 项目架构

### 整体布局

页面采用**三栏布局**，各面板支持折叠/展开：

```
+-------------------+---------------------------+-------------------+
|                   |                           |                   |
|   对话历史区       |      3D 视图区             |   右侧面板        |
|   (ChatPanel)     |      (Viewport3D)         |   (RightPanel)    |
|   320px 固定宽度  |      自适应剩余宽度        |   320px 固定宽度  |
|                   |                           |                   |
|   - 消息列表       |   - Three.js Canvas       |   Tab 1: 属性/图层 |
|   - 输入框         |   - 轨道控制              |   Tab 2: 数据集    |
|   - 新建对话       |   - 工具栏浮层            |                   |
|                   |                           |                   |
+-------------------+---------------------------+-------------------+
```

### 数据流

```
用户输入文字
    |
    v
ChatPanel 触发 CustomEvent('cad:generate')
    |
    v
App.tsx 监听事件 -> 调用 api.ts (mock API)
    |
    v
轮询 pollTaskStatus 直到任务完成
    |
    v
更新 Zustand store (sceneModels / messages)
    |
    v
Viewport3D / ChatPanel / RightPanel 自动响应 store 变化重新渲染
```

### 状态管理（Zustand Store）

Store 管理以下状态域：

- **对话状态**：`messages`（消息列表）、`sessionId`、`isGenerating`
- **场景模型**：`sceneModels`（3D 模型数组）、`selectedModelId`
- **数据集**：`datasetEntries`（已保存条目列表）、`selectedDatasetEntryId`
- **UI 状态**：面板折叠状态、当前 Tab、线框模式

## 文件夹结构与文件说明

```
text-to-cad/
├── index.html                 # HTML 入口，挂载 #root 节点
├── package.json              # 项目配置与依赖声明
├── tsconfig.json             # TypeScript 编译配置（含 JSX）
├── tsconfig.node.json        # Vite 配置文件的 TypeScript 编译配置
├── vite.config.ts            # Vite 构建配置（React + TailwindCSS 插件）
├── public/
│   ├── favicon.svg           # 网站图标
│   └── icons.svg             # 备用图标资源
└── src/
    ├── main.tsx              # React 应用入口，挂载 <App /> 到 DOM
    ├── App.tsx               # 根组件：三栏布局组装 + 生成流程控制
    ├── index.css             # TailwindCSS 导入 + 自定义暗色主题变量 + 全局样式
    ├── vite-env.d.ts         # Vite 环境类型声明（CSS 模块等）
    ├── types.ts              # 全局 TypeScript 类型定义
    ├── store.ts              # Zustand 状态管理（对话、模型、数据集、UI）
    ├── api.ts                # Mock API 层（模拟后端接口，保留 Axios 结构）
    └── components/
        ├── ChatPanel.tsx     # 左侧对话历史面板
        ├── Viewport3D.tsx    # 中央 3D 视图（Three.js 场景）
        └── RightPanel.tsx    # 右侧面板（属性/图层 + 数据集管理）
```

### 各文件职责

| 文件 | 职责 |
|------|------|
| `main.tsx` | 创建 React 根节点，渲染 App 组件 |
| `App.tsx` | 组装三栏布局，监听生成事件，编排 API 调用与轮询逻辑 |
| `types.ts` | 定义 `SceneModel`、`ChatMessage`、`DatasetEntry`、`GenerationTask` 等接口 |
| `store.ts` | Zustand store，管理全部全局状态及操作方法，预置 3 条数据集条目 |
| `api.ts` | Mock 后端 API（`generateModel`、`pollTaskStatus`、数据集 CRUD），内含自然语言解析逻辑 |
| `index.css` | TailwindCSS 主题配置（暗色色板变量）、自定义滚动条、代码块样式 |
| `ChatPanel.tsx` | 对话消息列表、用户/系统消息气泡、模型卡片、复制/重新生成、输入框 |
| `Viewport3D.tsx` | Three.js Canvas、几何体渲染、轨道控制、网格辅助、光照、工具栏（重置/线框/截图） |
| `RightPanel.tsx` | Radix Tabs 切换；属性面板（参数滑块、体积/表面积计算）；图层面板（可见性/删除）；数据集网格、搜索、添加弹窗、详情子标签页（6 个字段） |

## Mock API 接口

当前所有后端接口使用 `setTimeout` 模拟延迟，保留真实 Axios 请求结构，便于后续接入真实后端。

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/generate` | POST | 接收 `{text, sessionId}`，返回 `taskId`，异步模拟生成流程 |
| `/api/generate/{taskId}` | GET | 轮询任务状态（pending -> processing -> completed） |
| `/api/dataset/list` | GET | 返回数据集条目列表 |
| `/api/dataset/entry` | POST | 添加新数据集条目 |
| `/api/dataset/entry/{id}` | GET | 获取条目详情 |
| `/api/dataset/entry/{id}` | DELETE | 删除条目 |

## 交互流程

1. 用户在左下角输入框输入描述（如"生成一个半径为2的球体"），按 Enter 或点击发送
2. 系统显示加载状态，后台轮询生成任务
3. 任务完成后，3D 视图自动切换为对应几何体，对话区增加带模型卡片的系统回复
4. 点击 3D 视图中的模型，右侧属性面板显示参数滑块，可实时调整尺寸
5. 切换到"数据集"Tab，点击"添加当前设计"保存到数据集
6. 单击数据集卡片查看详情（6 个子标签页），双击加载到 3D 视图
