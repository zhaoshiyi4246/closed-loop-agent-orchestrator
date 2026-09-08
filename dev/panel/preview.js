/* Dev-only transport fixtures. Product app.js has no sample mode or branches.
 * CSP blocks network connections; the dev server also rejects every POST.
 */
const choice=new URLSearchParams(location.search).get("state") || "empty";
const sampleName=Object.hasOwn(PREVIEW_STATES,choice)?choice:"empty";
const banner=document.createElement("aside");banner.className="notice warning";
banner.setAttribute("aria-label","开发样例");
const label=document.createElement("label");label.textContent="开发样例 · 不连接真实任务 ";
const selector=document.createElement("select");selector.id="devState";
for(const [value,title] of Object.entries(PREVIEW_STATES)){
  const option=document.createElement("option");option.value=value;option.textContent=title;selector.append(option);
}
selector.value=sampleName;
selector.onchange=()=>{location.search="?state="+encodeURIComponent(selector.value);};
label.append(selector);banner.append(label);document.getElementById("main").prepend(banner);

window.fetch=async (url,options={})=>{
  const path=new URL(url,location.href).pathname;
  let data,status=200;
  if(path==="/api/projects/source") data={ok:true,source:{project_id:"sample-project",path:"示例项目 / data-tools",revision:"sample-only",file_count:1,bytes:0,files:[{path:"app.py"}],excluded:[]}};
  else if((options.method || "GET")!=="GET") {data={ok:false,error:"开发样例不执行写操作。"};status=403;}
  else if(path==="/api/projects") data={ok:true,projects:[{id:"sample-project",name:"示例 · 数据工具",path:"示例项目 / data-tools",kind:"git"}]};
  else if(path==="/api/file") data={ok:true,content:"样例运行投影；未读取真实任务文件。"};
  else {data={ok:false,error:"没有此开发夹具"};status=404;}
  return new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json"}});
};
let sequence=0;
window.EventSource=class {
  constructor(){
    this.timer=setTimeout(()=>{
      const snapshot=previewSnapshot(sampleName);
      snapshot.stream={epoch:"dev-sample",sequence:++sequence};
      this.onmessage?.({data:JSON.stringify(snapshot)});
      if(sampleName==="disconnected") this.onerror?.(new Event("error"));
    },0);
  }
  close(){clearTimeout(this.timer);}
};
