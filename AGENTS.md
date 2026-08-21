# AGENTS.md

> 本文件供 AI 编码代理快速理解项目**当前**状态。事实取自代码；`[推断]` 为基于代码的合理推断。

## 项目

`mcp-feedback-enhanced`（增强 fork，PyPI 分发名 `mcp-feedback-pro`）是一个 **MCP 服务器**，为 AI 辅助开发提供"以反馈为导向"的交互工作流，提供 **Web UI 与桌面应用（Tauri）双界面**，适配本地、SSH 远程与 WSL 环境。`[推断]` 定位为通用反馈收集中介层（fork 自 interactive-feedback-mcp）。

## 技术栈

- 语言/运行时：Python >=3.11（3.11/3.12）；桌面端 Rust（Tauri，见 `src-tauri/`）；Web 前端为原生模块化 JS（无打包器）。
- MCP 框架：FastMCP；Web：FastAPI + Starlette + Uvicorn + Jinja2 + WebSockets。
- 包管理/构建：`uv` + `uv.lock`；构建后端 `hatchling`（`maturin`/`setuptools-rust` 仅用于桌面二进制）。
- 质量：ruff（line-length 88、双引号、target py311）+ mypy（渐进式）；测试 pytest + pytest-asyncio。
- 发布：PyPI 包名 `mcp-feedback-pro`；CI 见 `.github/workflows/publish.yml`。

## 命令

```bash
uv sync --dev                 # 安装依赖（含 dev）
uv run pytest                # 运行单测
uv run ruff check .          # lint
uv run ruff format .         # 格式化
uv run mypy                  # 类型检查
uv build                     # 构建 wheel + sdist 到 dist/
uv run twine check dist/*    # 校验包
uv run bump2version patch    # 升版（patch/minor/major）
uv run twine upload dist/*   # 发布到 PyPI（读取 ~/.pypirc）
make build-desktop-release   # 构建桌面二进制（需 Rust + tauri-cli）
```

> 注：`uv publish` 不读取 `~/.pypirc` 凭证，本地发布请用 `twine upload`（已验证）。完整发版流程（TAG 自动发版）见 `docs/RELEASE.md`。

## 架构

- `src/mcp_feedback_enhanced/`：主包。入口 `server.py` / `__main__:main`；提供三个控制台命令别名（`mcp-feedback-pro`、`mcp-feedback-enhanced`、`interactive-feedback-mcp`）均指向同一入口。
- `src/mcp_feedback_enhanced/web/`：Web UI 子系统 —— `routes/`（FastAPI 路由）、`models/`（会话/反馈数据模型）、`static/`（模块化 JS：websocket-manager、app 等）、`templates/`（Jinja2）、`locales/`（i18n）。
- `src/mcp_feedback_enhanced/desktop_app/` + `src-tauri/`：Tauri 桌面应用（Rust）；`desktop_release/` 存放预构建二进制（直接提交 Git）。
- `docs/`（架构/提案/工作流）、`examples/`、`scripts/`（含 `release.py` 本地发布脚本）、`RELEASE_NOTES/`（多语 CHANGELOG）、`tests/`。

## 约定

- 布局：src-layout（`src/mcp_feedback_enhanced`），`[tool.hatch.build.targets.wheel].packages` 指定；相对导入（`TID252` 保留）。
- 语言：`[推断]` 代码注释、CHANGELOG、提交信息用中文；用户可见文案经 `web/locales` 做 i18n（zh-TW/en/zh-CN）。
- 发布：bump2version 升版 + 打 tag `vX.Y.Z`；CI 经 `secrets.PYPI_API_TOKEN` 发布并建 GitHub Release。`scripts/release.py` 为本地发布脚本（交互式）。
- 质量门禁（CI 模拟 `make ci`）：pre-commit → ruff → mypy → pytest。大量 ruff 规则在 pyproject 显式 ignore（含中文全角字符 `RUF001/2/3`、裸 except、复杂度等）。
- 类型：mypy `disallow_untyped_defs=false`（渐进式），第三方库 `ignore_missing_imports`。

## 规则

- 安全：`web/` 仅绑定 `127.0.0.1`（`S104` 仅在 web 放开）；WebSocket 入站须按消息重解析当前会话归属（反馈路由修复，见 `web/routes/main_routes.py`）。不要在未持 session 校验的接口上暴露能力。
- 发布：本地发布用 `twine upload`（非 `uv publish`）；发布前**必须升版**——PyPI 拒绝重复版本号。
- 包名：已更名为 `mcp-feedback-pro`（PyPI 当前 2.10.1）；`mcp-feedback-enhanced` 包仅停留在 2.6.0。文档安装命令须用 `uvx mcp-feedback-pro@latest`，不可用旧的 `mcp-feedback-enhanced@latest`（会装到过期版本）。
- 改动边界：`[推断]` 只改与需求直接相关的代码，不顺手修改既有 lint 忽略项或无关模块；保持 src-layout 与相对导入。
- 提交/PR：`[推断]` 用中文描述；版本号遵循语义化（patch=缺陷修复）。
