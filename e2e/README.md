# Playwright E2E

这里的测试会用真实 Chromium 打开 `http://127.0.0.1:8688`，像用户一样点击页面。
它不参与 `web/` 的运行，也不需要前端构建；只是开发阶段的质量检查。

## 第一次准备

```powershell
# 在项目根目录执行一次
npm install
```

如果 `npm` 不在 PATH，可以直接用已安装好的 Node 运行 Playwright，不需要 npm：

```powershell
node node_modules/@playwright/test/cli.js test
```

## 运行

```powershell
# 无头模式，跑全部用例
node node_modules/@playwright/test/cli.js test

# 看见浏览器窗口，方便观察每一步
node node_modules/@playwright/test/cli.js test --headed

# 只跑名字里带“登录”的用例
node node_modules/@playwright/test/cli.js test -g "登录"

# 查看上次失败的报告
node node_modules/@playwright/test/cli.js show-report
```

服务没启动也没关系：`playwright.config.js` 的 `webServer` 会自动启动 uvicorn。
如果 8688 已经有服务，它会直接复用，不会启动第二个进程。

## 登录后的用例

`登录后进入问答界面` 默认跳过。想跑它，先设置真实账号：

```powershell
$env:E2E_USERNAME = "your-user"
$env:E2E_PASSWORD = "your-password"
node node_modules/@playwright/test/cli.js test
```

不要把账号密码写进测试文件，也不要把它们提交到仓库。

## 配置说明

- `channel: "chromium"`：使用已下载的完整 Chromium，避免再下载 `chromium-headless-shell`。
- `workers: 1`：SQLite 和 Qdrant 都是单进程约束，E2E 也不并发。
- `reuseExistingServer: true`：优先复用正在运行的服务。
- 失败时自动保存截图和 trace，产物在 `test-results/`，已被 `.gitignore` 忽略。

## 常见问题

**提示缺少 `chromium-headless-shell`**

配置已经用 `channel: "chromium"` 绕开它。如果自己新写了配置，要么保留这个 channel，
要么执行：

```powershell
npx playwright install chromium-headless-shell
```

**端口被占用 / Qdrant 文件锁**

不要同时启动第二个 uvicorn。先确认 8688 上跑的是当前服务，再运行测试。

**页面打开是旧样式或旧 JS**

服务端已对 `/static` 返回 `no-cache`，一般刷新即可；必要时 Ctrl+F5。
