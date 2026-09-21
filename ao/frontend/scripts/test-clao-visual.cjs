// Actual native theme controls and Chromium zoom. capturePage avoids Playwright
// viewport clipping at Electron's non-default zoom levels.
const path=require('path');
module.exports=async({page,app,evidence,objective})=>{
 await page.getByRole('button',{name:'关闭',exact:true}).click();
const capture=async name=>{const shot=await app.evaluate(async({webContents})=>{const w=webContents.getAllWebContents().find(w=>w.getURL().startsWith('http://localhost:5173'));return (await w.capturePage()).toPNG().toString('base64');});require('fs').writeFileSync(path.join(evidence,name+'.png'),Buffer.from(shot,'base64'));};
for(const theme of ['light','dark']) {
 await page.getByRole('button',{name:'Settings',exact:true}).first().click();
 await page.getByRole('button',{name:'Theme',exact:true}).click();
 await page.getByRole('menuitem',{name:theme==='light'?'Light':'Dark',exact:true}).click();
 await page.getByRole('button',{name:'Close settings',exact:true}).click();
 await page.getByRole('button',{name:'查看原请求：'+objective,exact:true}).click();
 const graph=page.getByRole('dialog').getByTestId('clao-run-view');
 for(const [width,zoom] of [[1440,1],[960,1],[1440,2]]) {
  await app.evaluate(({BaseWindow,webContents},{width,zoom})=>{BaseWindow.getAllWindows()[0].setSize(width,900);webContents.getAllWebContents().filter(w=>w.getType()==='window').forEach(w=>w.setZoomFactor(zoom));},{width,zoom});
  await page.waitForTimeout(500);await graph.scrollIntoViewIfNeeded();
  const layout=await page.evaluate(()=>{const d=document.querySelector('[role=dialog]'),r=d.getBoundingClientRect();return {theme:document.documentElement.dataset.theme,width:innerWidth,height:innerHeight,rect:{x:r.x,y:r.y,width:r.width,height:r.height},overflow:d.scrollWidth>d.clientWidth+2};});
  console.log('VISUAL',theme,width,zoom,JSON.stringify(layout));
  if(layout.theme!==theme||layout.overflow||layout.rect.x<0||layout.rect.x+layout.rect.width>layout.width+2)throw Error('visual bounds or theme mismatch');
  await capture(`native-${theme}-${width}-${zoom===2?'200pct':'100pct'}`);
 }
 await app.evaluate(({BaseWindow,webContents})=>{BaseWindow.getAllWindows()[0].setSize(1440,900);webContents.getAllWebContents().filter(w=>w.getType()==='window').forEach(w=>w.setZoomFactor(1));});
 await page.getByRole('button',{name:'关闭',exact:true}).click();
}
await page.getByRole('button',{name:'Settings',exact:true}).first().click();
await page.getByRole('button',{name:'模型连接与迁移',exact:true}).click();
await page.getByRole('button',{name:'新建模型连接',exact:true}).click();
await page.getByLabel('连接名称').fill('收尾验证连接');
await page.getByLabel('模型服务').selectOption('bigmodel_general');
await page.getByLabel('搜索 API 型号').fill('5.3');
await page.getByRole('button',{name:/^glm-5.3$/i}).click();
await page.getByRole('button',{name:'保存连接',exact:true}).click();
await page.getByText('已保存 收尾验证连接。请配置系统凭据；尚未发送模型请求。',{exact:true}).waitFor();
await capture('new-model-connection');
await page.getByRole('button',{name:'Close settings',exact:true}).click();
await page.getByRole('button',{name:'查看原请求：'+objective,exact:true}).click();
console.log('NATIVE_VISUAL_AND_CONNECTION_PASS');
};
