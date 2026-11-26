// Playwright 端到端测试配置。
// 只测真实浏览器里的用户流程，不参与 web/ 的运行时，也不需要前端构建。
const { defineConfig } = require('@playwright/test');

const baseURL = process.env.E2E_BASE_URL || 'http://127.0.0.1:8688';

module.exports = defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  // SQLite / Qdrant 都是单进程约束，E2E 也保持单 worker。
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL,
    // 用完整 Chromium，不走未安装的 chromium-headless-shell。
    channel: 'chromium',
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    // 已有服务时直接复用，避免第二个 uvicorn 抢 SQLite / Qdrant 文件锁。
    command: '.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8688',
    url: baseURL,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
