# 发版流程 (Release Process)

本项目的发布目标为 PyPI 包 **`mcp-feedback-pro`**（旧包名 `mcp-feedback-enhanced` 仅停留在 2.6.0，已弃用）。发版采用「打 TAG 自动发版」机制：向 `main` 分支推送 `v*` TAG 即触发 GitHub Actions 自动构建、发布到 PyPI 并创建 GitHub Release。

## 前置条件

- 仓库已配置 **`PYPI_API_TOKEN`** Secret（`Settings → Secrets and variables → Actions`）。`release.yml` 用它向 PyPI 发布。
- 本地 `~/.pypirc` 含 `[pypi]` 凭证（用于本地 `twine upload` 手动发版）。

## 标准发版流程（推荐：TAG 触发自动发版）

1. **升版**

   ```bash
   uv run bump2version patch   # 或 minor / major
   ```

   会同步更新 `pyproject.toml` 与 `src/mcp_feedback_enhanced/__init__.py` 的版本号。

2. **（可选）更新 CHANGELOG**

   在 `RELEASE_NOTES/CHANGELOG.en.md`、`CHANGELOG.zh-TW.md`、`CHANGELOG.zh-CN.md` 新增对应版本小节。缺少该版本小节时 `release.yml` 仅给出警告，不阻断发布。

3. **提交**

   ```bash
   git commit -am "🔖 Release vX.Y.Z"
   ```

4. **打 TAG**

   ```bash
   git tag vX.Y.Z
   ```

5. **推送分支与 TAG**

   ```bash
   git push origin main          # 先推分支（含发版提交）
   git push origin vX.Y.Z        # 再推【单个】TAG 触发自动发版（关键）
   ```

   > ⚠️ **务必逐 TAG 推送，勿用 `git push origin --tags`**：一次性批量推多个 TAG 时，GitHub 对其中某个 TAG 的 push 事件可能投递丢失（已知 "On Create Tags" 间歇性不触发问题），导致自动发版未触发；且 `--tags` 会把本地历史旧 TAG 一并推上 origin。

6. **自动发版**

   推送 `v*` TAG 后，`.github/workflows/release.yml` 自动执行：

   - 校验 `pyproject.toml` 的 `version` 与 TAG 一致（不一致直接失败）；
   - `uv build` 构建 wheel + sdist 到 `dist/`；
   - `uv run twine check` 校验包；
   - `pypa/gh-action-pypi-publish` 发布到 PyPI（使用 `secrets.PYPI_API_TOKEN`）；
   - `softprops/action-gh-release` 创建 GitHub Release（自动生成 Release Notes，附 `dist/*`）。

## 本地手动发版（备用）

```bash
uv build
uv run twine check dist/*
uv run twine upload dist/*     # 读取 ~/.pypirc 凭证
```

> ⚠️ **不要用 `uv publish` 发版**：它不读取 `~/.pypirc` 凭证，会报 `Missing credentials` 失败。
> 项目自带 `scripts/release.py`（`python scripts/release.py patch|minor|major`）走 `twine upload` 流程，亦可手动交互式发布。

## 关键约束

- **必须升版**：PyPI 拒绝重复版本号，未升版直接重试发布会失败。
- **不要重复推送已发布版本的 TAG**：例如 `v2.10.1` 已发布，不要再推送该 TAG（会触发对已发布版本的重复发布，PyPI 拒绝）。
- 桌面二进制（`desktop_release/` 下的 4 个平台文件）已提交进仓库，会自动打进 wheel，`release.yml` 无需重新编译（故未安装 Rust 工具链）。

## 相关文件

- `.github/workflows/release.yml`：TAG 触发自动发版工作流（本流程主力）。
- `.github/workflows/publish.yml`：手动 `workflow_dispatch` 发版流程（含桌面构建编排，可作后备）。
- `scripts/release.py`：本地发布脚本。
- `RELEASE_NOTES/CHANGELOG.*.md`：多语发布说明。
