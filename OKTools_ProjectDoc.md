# OK-Tools 项目文档（规划版）

## 1. 目标与范围
### 1.1 已确认
- 丹青模拟器：现有逻辑基本 OK，保留现有核心并迁移到新架构。

### 1.2 需要适配
- 天书模拟器：计划重构，使其符合 ok-script 架构与桌面化使用方式。

### 1.3 纯 Python 新工具
- 交易行工具
- 鸿钧自动抢线
- 钓鱼工具

### 1.4 WebView 方式
- 其它未迁移或强依赖网页的工具，直接用 WebView 指向服务器页面。
- Guide 模板单独作为一个“工具”对待，同样走 WebView 或本地渲染方式。

### 1.5 需要重点解决的问题
- 软件更新机制
- 交易行数据拉取与备用源策略
- 本地数据存储优化（离线可用、数据一致）

---

## 2. 总体架构
### 2.1 架构核心
- 基于 ok-script 构建桌面应用主程序。
- 每个“工具”作为独立模块挂载到主菜单。
- UI参考  这个项目的 https://github.com/ok-oldking/ok-wuthering-waves 项目的 UI 设计。

### 2.2 工具分类
1. 本地运行模块（Python）
   - 丹青模拟器、交易行、抢线、钓鱼
2. WebView 模块
   - 其它工具、Guide 模板页

---

## 3. 新项目目录建议（新文件夹）
```
ok-ZhuXian World/
├─ main.py
├─ app/
│  ├─ ui/                # 主界面、菜单、面板
│  ├─ core/              # 统一工具调度、状态管理
│  ├─ storage/           # 本地数据读写、版本管理
│  ├─ update/            # 更新与下载逻辑
│  └─ webview/           # WebView 封装
├─ tools/
│  ├─ danqing/
│  ├─ zhuangbei/
│  ├─ tianshu/
│  ├─ jiaoyihang/
│  ├─ hongjun/
│  └─ diaoyu/
├─ assets/
│  ├─ icons/
│  └─ data/
└─ config/
   ├─ app.json           # 应用设置
   └─ tools.json         # 工具清单与入口
```

---

## 4. 各工具改造计划
### 4.1 丹青模拟器
- 保留现有模拟核心
- 提供统一入口函数（例如 simulate(deck_ids, level, base_atk, base_dps)）
- 前端部分暂不迁移，桌面端先做“输入 + 结果展示”最简版本

### 4.2 天书模拟器（重构方向）
- 从网页组件拆出“数据层”和“逻辑层”
- 目标：可在桌面端复用数据和核心逻辑
- 建议拆分为：
  - data: 天书树与技能数据
  - logic: 加点与校验、统计汇总
  - ui: ok-script 的面板展示

### 4.3 交易行工具
- 纯 Python 逻辑直接迁移
- 增加数据缓存与版本号
- 查询与刷新分离（避免频繁拉取）

### 4.4 鸿钧自动抢线 / 钓鱼工具
- 按 ok-script 任务模型封装
- 加入“安全退出、可视化状态、日志面板”

### 4.5 WebView 工具
- 工具清单里配置 URL
- 支持本地缓存（首次打开拉取资源，离线可读）

---

## 5. 数据与本地存储方案
### 5.1 本地存储目标
- 离线可用
- 版本可追踪
- 数据结构稳定

### 5.2 建议存储形态
- 小量数据：JSON 文件
- 结构化、查询频繁：SQLite

### 5.3 统一数据层设计
```
storage/
├─ app.db              # SQLite
├─ cache/
│  └─ market.json
└─ meta/
   └─ versions.json    # 数据版本与更新时间
```

---

## 6. 更新与数据拉取策略
### 6.1 软件更新
- 主策略：GitHub Release 版本更新
- 项目地址：https://github.com/massimowei/ok-ZhuXian-World
- ok-script 支持在线增量更新，可直接对接发布机制
- 客户端更新流程：
  1. 启动时检查最新版本号
  2. 比较版本号
  3. 下载与应用更新

### 6.2 交易行数据拉取（双源）
- 主源：GitHub Raw（稳定、版本可控）
- 备用源：自有服务器（可自定义更新频率）

### 6.3 推荐拉取流程
1. 读取本地版本号
2. 拉取主源版本号
3. 若失败，拉取备用源版本号
4. 版本号高于本地则下载
5. 下载失败则保留本地旧数据

### 6.4 失败兜底
- 主源失败自动切换备用源
- 备用源失败使用本地缓存
- 本地缓存失效时提示用户离线模式

---

## 7. 工具清单配置示例（tools.json）
```json
[
  { "id": "danqing", "name": "丹青模拟器", "type": "python", "entry": "tools/danqing/entry.py" },
  { "id": "tianshu", "name": "天书模拟器", "type": "python", "entry": "tools/tianshu/entry.py" },
  { "id": "market", "name": "交易行工具", "type": "python", "entry": "tools/market/entry.py" },
  { "id": "hongjun", "name": "鸿钧抢线", "type": "python", "entry": "tools/hongjun/entry.py" },
  { "id": "fishing", "name": "钓鱼工具", "type": "python", "entry": "tools/fishing/entry.py" },
  { "id": "guides", "name": "游戏攻略", "type": "webview", "url": "https://your-server/guide" }
]
```

---

## 8. 里程碑建议
1. 搭建 ok-script 主程序骨架与工具菜单
2. 迁移丹青模拟器并跑通
3. 交易行工具整合与数据更新机制打通
4. 天书模拟器重构完成
5. 抢线、钓鱼工具接入
6. WebView 工具与 Guide 版块上线
7. 更新与发布流程走通

---

## 9. 风险点与预案
- Python 版本固定为 3.12 （ok-script 要求）
- 数据源不可用时保证可离线运行
- WebView 工具应提供“打开外部浏览器”的备用入口

---

## 10. 下一步落地清单
- 创建新项目文件夹 ok-tools
- 把丹青模拟器 Python 核心复制到 tools/danqing
- 写 entry.py 作为统一入口
- 设计 tools.json 并实现菜单加载
- 接入更新与数据拉取模块
