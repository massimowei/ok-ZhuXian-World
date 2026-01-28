# OK-ZhuXian World

一个本地桌面工具箱（Python），目前包含：

- 丹青模拟器（本地计算）
- 游戏日历（离线版：任务管理 + 活动日历，不需要联网）

## 环境要求

- Windows
- Python 3.12（必须）

## 安装依赖

在项目目录打开 PowerShell：

```powershell
cd "XXXXX\Ok-ZhuXian World"

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -U pip
pip install -r requirements.txt
```

## 运行

```powershell
cd "XXXXX\Ok-ZhuXian World"
.\.venv\Scripts\Activate.ps1
python main.py
```

说明：

- 程序会优先启动 Qt UI；如果 Qt 启动失败，会自动回退到 Tkinter UI。
- “游戏日历”目前在 Qt UI 中可用（离线版）。

## 本地数据存储

“游戏日历”的进度会保存到：

- `tools/rili/storage/game-task-manager-v1.json`
- `tools/rili/storage/activity-calendar-v1.json`

这些是个人进度文件，默认已在 `.gitignore` 里忽略，不会提交到仓库。

## 目录结构（简要）

- `main.py`：程序入口（优先 Qt，失败回退 Tkinter）
- `app/ui/qt_toolbox.py`：Qt 工具箱 UI
- `app/ui/toolbox.py`：Tkinter 回退 UI
- `tools/`：各个工具模块
- `config/tools.json`：工具清单配置
