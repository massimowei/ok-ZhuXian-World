# OK-ZhuXian World

一个本地桌面工具箱（Python），目前包含：

- 丹青模拟器（本地计算）
- 游戏日历（离线版：任务管理 + 活动日历，不需要联网）
- 天书模拟器（离线版，内置页面）
- 资料库（离线版：交易行/装备）
- 鸿钧（自动化工具）

## 环境要求

- Windows
- Python 3.12（必须）

## 安装依赖

在项目目录打开 PowerShell：

```powershell
cd "D:\path\to\ok-ZhuXian-World"

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -U pip
pip install -r requirements.txt
```

## 运行

```powershell
cd "D:\path\to\ok-ZhuXian-World"
.\.venv\Scripts\Activate.ps1
python main.py
```

说明：

- 程序会优先启动 Qt UI；如果 Qt 启动失败，会自动回退到 Tkinter UI。
- “天书模拟器 / 游戏日历 / 资料库 / 鸿钧”在 Qt UI 中可用。

## 本地数据存储

“游戏日历”的进度会保存到：

- `tools/rili/storage/game-task-manager-v1.json`
- `tools/rili/storage/activity-calendar-v1.json`

这些是个人进度文件，默认已在 `.gitignore` 里忽略，不会提交到仓库。

若使用安装包安装（PyInstaller + Setup），用户数据会写入到：

- `%LOCALAPPDATA%\OK-ZhuXian World\storage\...`

## 打包（Windows Setup）

本项目使用 PyInstaller 生成 `dist/OK-ZhuXian-World/`，再用 Inno Setup 生成安装包。

```powershell
cd "D:\path\to\ok-ZhuXian-World"
.\.venv\Scripts\Activate.ps1

python -m pip install -U pyinstaller pillow
python -m PyInstaller ... main.py

"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "installer.iss"
```

产物：

- `dist/OK-ZhuXian-World/OK-ZhuXian-World.exe`
- `dist/installer/OK-ZhuXian-World-Setup.exe`

## 目录结构（简要）

- `main.py`：程序入口（优先 Qt，失败回退 Tkinter）
- `app/ui/qt_toolbox.py`：Qt 工具箱 UI
- `app/ui/toolbox.py`：Tkinter 回退 UI
- `tools/`：各个工具模块
- `config/tools.json`：工具清单配置
