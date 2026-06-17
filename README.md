# 朋友圈助手

多账号朋友圈自动化发布工具。Python 实现，Mac 开发，Windows 运行。

---

## 快速开始（Mac 开发环境）

```bash
# 1. 建虚拟环境
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate

# 2. 装依赖
pip install -r requirements.txt

# 3. 配置私钥（开发用）
echo "WM_PRIVATE_KEY=你的私钥" > .env

# 4. 生成测试注册码
python src/auth.py

# 5. 启动
python src/main.py
```

Mac 上会用 mock 微信窗口，GUI 和调度逻辑可以完整测试，图像识别和真实发布需要 Windows 验证。

---

## Windows 部署

```bat
:: 1. 安装 Python 3.12，建虚拟环境
python -m venv .venv
.venv\Scripts\activate

:: 2. 装依赖
pip install -r requirements.txt

:: 3. 用多开工具登录好所有微信账号

:: 4. 截图 templates/ 里的 4 张按钮模板（见下）

:: 5. 启动
python src\main.py
```

---

## 模板图截图说明

首次在目标机器运行前，需截图 4 个微信按钮存入 `templates/`：

| 文件名 | 截图位置 |
|--------|---------|
| `moments_btn.png` | 微信主界面底部"朋友圈"按钮 |
| `camera_btn.png` | 朋友圈顶部相机图标 |
| `album_btn.png` | 发布弹窗里"从相册选择" |
| `post_btn.png` | 编辑页右上角"发表"按钮 |

截图要求：原始尺寸，不缩放，DPI 与运行时一致。微信更新后如果按钮样式变化，重新截图即可。

---

## 注册码

```bash
# 生成一批注册码（开发者工具，不发给用户）
python src/auth.py
```

私钥由 `WM_PRIVATE_KEY` 环境变量控制，默认值仅用于本地开发，发布前替换。

---

## 项目结构

```
src/
├── main.py               入口
├── auth.py               注册码验证
├── window_manager.py     窗口管理（Windows/Mac 分支）
├── image_recognition.py  OpenCV 模板匹配
├── publisher.py          发布流程
├── scheduler.py          调度 + 养号策略
└── gui/                  tkinter 界面
templates/                按钮截图模板
```

详细设计见 [项目方案总结.md](项目方案总结.md)，模块说明见 [完整代码实现.md](完整代码实现.md)。

---

## Mac vs Windows 能测什么

| 功能 | Mac | Windows |
|------|-----|---------|
| GUI 流程 | ✅ | ✅ |
| 激活 / 注册码 | ✅ | ✅ |
| 时间表生成 / 养号策略 | ✅ | ✅ |
| mock 发布（调度验证） | ✅ | ✅ |
| 真实微信窗口操作 | ❌ | ✅ |
| 图像识别找按钮 | ❌ | ✅ |
| 实际发布 | ❌ | ✅ |
