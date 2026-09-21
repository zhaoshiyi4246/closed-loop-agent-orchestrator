// Reuse the installed application's completed single-task profile. Only the
// external protocol fixture pauses its two Workers; no product state is forged.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

module.exports = async ({ page, app, evidence, env, missions, waitFor }) => {
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: 'New task', exact: true }).first().click();
  await page.getByRole('dialog').waitFor();
  const fresh = page.getByRole('button', { name: '创建新的尝试（保留草稿）', exact: true });
  if (await fresh.isVisible()) await fresh.click();
  await page.getByLabel('CLAO 闭环验收').check();
  await page.getByLabel('使用上述当前内容快照').check({ timeout: 20000 });
  await page.getByLabel('验收条件（每行一项）').fill('left.txt accepted\nright.txt accepted');
  await page.getByLabel('检查命令（每行一条）').fill('python check.py left.txt\npython check.py right.txt');
  await page.getByLabel('允许修改范围').fill('left.txt\nright.txt');
  await page.getByLabel('最多修复次数').fill('0');
  await page.getByLabel('执行安排').selectOption('2');
  await page.getByRole('button', { name: 'Agent', exact: true }).click();
  await page.getByRole('menu').getByText('opencode', { exact: true }).click();
  await page.getByRole('button', { name: 'Model', exact: true }).click();
  await page.getByRole('menu').getByText('test/native', { exact: true }).click();
  const objective = 'Installed independent parallel outputs';
  await page.getByRole('textbox', { name: 'Task', exact: true }).fill(objective);
  await page.getByRole('button', { name: 'Start task', exact: true }).click();
  const dual = await waitFor(async () => (await missions()).find(m => m.request.objective === objective && m.subtasks?.length === 2 && m.subtasks.every(child => child.sessionId)), 'Two installed Worker Sessions not created');
  assert.equal(new Set(dual.subtasks.map(m => m.sessionId)).size, 2);
  if (!await page.getByRole('dialog').isVisible()) await page.getByRole('button', { name: '查看原请求：' + objective, exact: true }).click();
  await app.evaluate(({ BaseWindow }) => BaseWindow.getAllWindows()[0].setSize(1440, 1000));
  const graph = page.getByRole('dialog').getByTestId('clao-run-view');
  assert.equal(await graph.count(), 1, 'Parallel task must have one total graph');
  const workers = graph.getByRole('button', { name: /执行任务/ });
  await waitFor(async () => await workers.count() === 2 && await graph.locator('button[data-state="active"]').filter({ hasText: '执行任务' }).count() === 2, 'Both installed Workers must be active together');
  for (let i = 0; i < 2; i++) {
    await workers.nth(i).click();
    assert.equal(await workers.nth(i).getAttribute('aria-pressed'), 'true');
    assert.equal(await workers.nth(1 - i).getAttribute('aria-pressed'), 'false');
    await graph.getByRole('region', { name: '执行任务记录', exact: true }).getByRole('button', { name: '打开对应会话', exact: true }).waitFor();
  }
  const capture = async name => {
    const png = await app.evaluate(async ({ webContents }, url) => (await webContents.getAllWebContents().find(w => w.getType() === 'window' && w.getURL() === url).capturePage()).toPNG().toString('base64'), page.url());
    fs.writeFileSync(path.join(evidence, name + '.png'), Buffer.from(png, 'base64'));
  };
  await graph.scrollIntoViewIfNeeded();
  await capture('installed-two-workers-active');
  const route = '**/api/v1/clao/missions**';
  await page.route(route, request => request.abort('failed'));
  try {
    await graph.getByText('连接中断 · 以下为最后已知记录，非实时活动。', { exact: true }).waitFor({ timeout: 15000 });
    assert.equal(await graph.locator('button[data-state="active"]').count(), 0);
    await capture('installed-two-workers-disconnected');
  } finally { await page.unroute(route); }
  await waitFor(async () => await graph.locator('button[data-state="active"]').filter({ hasText: '执行任务' }).count() === 2, 'Worker activity did not recover after actual transport recovery');
  fs.writeFileSync(env.CLAO_FIXTURE_PARALLEL_RELEASE, 'release');
  const done = await waitFor(async () => {
    const m = (await missions()).find(m => m.request.id === dual.request.id);
    if (['FAILED', 'UNKNOWN', 'HUMAN'].includes(m.state)) throw Error(m.reason);
    return m.state === 'DONE' ? m : null;
  }, 'Installed integrated mission did not finish');
  assert(done.resultHead && done.subtasks.every(m => m.state === 'DONE' && m.resultHead));
  assert.equal(done.evidence.at(-1)?.verification?.verdict, 'PASS');
  assert(done.evidence.at(-1)?.ok && done.evidence.at(-1)?.scopeOK);
  assert(done.verifierSessionId && !done.subtasks.some(m => m.sessionId === done.verifierSessionId));
  await page.getByRole('dialog').getByText('CLAO · 验收通过', { exact: true }).first().waitFor();
  assert.equal(await graph.count(), 1);
  assert.equal(await graph.locator('button[data-state="active"]').count(), 0);
  await capture('installed-two-workers-integrated');
  return { id: done.request.id, state: done.state, workers: done.subtasks.map(m => m.sessionId), verifier: done.verifierSessionId, nodeSelectionChecked: 2, singleGraph: true, transportLossChecked: true };
};
