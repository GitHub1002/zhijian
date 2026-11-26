// 冒烟 E2E：不需要账号，验证页面能打开、登录/注册表单可交互。
// 登录后的流程依赖真实账号，设置 E2E_USERNAME / E2E_PASSWORD 后才会运行。
const { test, expect } = require('@playwright/test');

test('首页加载并显示登录表单', async ({ page }) => {
  await page.goto('/');

  await expect(page).toHaveTitle(/智检/);
  await expect(page.getByRole('heading', { name: '登录 智检' })).toBeVisible();
  await expect(page.getByLabel('用户名')).toBeVisible();
  await expect(page.getByLabel('密码')).toBeVisible();
  await expect(page.getByRole('button', { name: '登录并进入' })).toBeVisible();
});

test('可以在登录和注册表单之间切换', async ({ page }) => {
  await page.goto('/');

  await page.getByRole('button', { name: '还没有账号？注册一个' }).click();
  await expect(page.getByRole('heading', { name: '注册知识库账号' })).toBeVisible();
  await expect(page.getByRole('button', { name: '注册并进入' })).toBeVisible();

  await page.getByRole('button', { name: '已有账号？返回登录' }).click();
  await expect(page.getByRole('heading', { name: '登录 智检' })).toBeVisible();
});

test('登录后进入问答界面', async ({ page }) => {
  const username = process.env.E2E_USERNAME;
  const password = process.env.E2E_PASSWORD;
  test.skip(!username || !password, '未设置 E2E_USERNAME / E2E_PASSWORD，跳过登录流程');

  await page.goto('/');
  await page.getByLabel('用户名').fill(username);
  await page.getByLabel('密码').fill(password);
  await page.getByRole('button', { name: '登录并进入' }).click();

  await expect(page.locator('#question')).toBeVisible();
  await expect(page.locator('#ask-btn')).toBeVisible();
});
