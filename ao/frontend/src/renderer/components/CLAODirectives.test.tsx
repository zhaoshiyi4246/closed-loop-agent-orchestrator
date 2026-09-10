import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { CLAODirectives } from './CLAODirectives';
import type { Mission } from './CLAOAcceptance';
const { api } = vi.hoisted(()=>({api:vi.fn()}));
vi.mock('./CLAOAcceptance',()=>({request:api}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const mission=(id:string,sid:string)=>({request:{id},state:'RUNNING',sessionId:sid,directives:[]} as unknown as Mission);
function setup(m:Mission){
 const client=new QueryClient();
 const view=(m:Mission)=><QueryClientProvider client={client}><CLAODirectives key={m.request.id} m={m} readError={false}/></QueryClientProvider>;
 const r=render(view(m));return {select:(m:Mission)=>r.rerender(view(m)),user:userEvent.setup()};
}
it.each(['相同草稿','不同的 B 草稿'])('A/B 接收对象与延迟回执隔离：%s',async bText=>{
 const a=mission(crypto.randomUUID(),'worker-a'),b=mission(crypto.randomUUID(),'worker-b');
 const {select,user}=setup(a);
 await user.selectOptions(screen.getByLabelText('指令接收对象'),'worker:worker-a');
 await user.type(screen.getByLabelText('补充要求'),'相同草稿');
 select(b);
 await user.selectOptions(screen.getByLabelText('指令接收对象'),'verifier');
 await user.type(screen.getByLabelText('补充要求'),bText);
 select(a);
 expect(screen.getByLabelText('指令接收对象')).toHaveValue('worker:worker-a');
 let release!:()=>void;let receipt:Record<string,unknown>={};
 api.mockImplementation(async(path:string,body?:Record<string,unknown>)=>{
  if(body){receipt={...body,state:'received'};await new Promise<void>(r=>release=r);return {directive:receipt};}
  expect(path).toBe('/missions/'+a.request.id);return {mission:{...a,directives:[receipt]}};
 });
 await user.click(screen.getByText('提交补充要求'));
 await waitFor(()=>expect(api).toHaveBeenCalledOnce());
 select(b);await act(async()=>release());
 expect(screen.getByLabelText('补充要求')).toHaveValue(bText);
 expect(screen.getByLabelText('指令接收对象')).toHaveValue('verifier');
 expect(screen.queryByText('已交付／已用于本轮输入')).not.toBeInTheDocument();
 select(a);await waitFor(()=>expect(screen.getByLabelText('补充要求')).toHaveValue(''));
 expect(screen.getByLabelText('指令接收对象')).toHaveValue('worker:worker-a');
 expect(api.mock.calls.filter(c=>c[1]).length).toBe(1);
});
it('同任务发送后重新编辑相同文本也不被旧回执清空',async()=>{
 const m=mission(crypto.randomUUID(),'worker-one');const {user}=setup(m);
 let release!:()=>void;let receipt={};
 api.mockImplementation(async(_path:string,body?:object)=>{if(body){receipt=body;await new Promise<void>(r=>release=r);return {};}
 return {mission:{...m,directives:[{...receipt,state:'received'}]}};});
 await user.type(screen.getByLabelText('补充要求'),'同文');await user.click(screen.getByText('提交补充要求'));
 await user.clear(screen.getByLabelText('补充要求'));await user.type(screen.getByLabelText('补充要求'),'同文');
 await act(async()=>release());await waitFor(()=>expect(screen.getByText('提交补充要求')).toBeEnabled());
 expect(screen.getByLabelText('补充要求')).toHaveValue('同文');
});
it('替换 Worker 不静默重定向草稿',async()=>{
 const m=mission(crypto.randomUUID(),'old-worker');const {user,select}=setup(m);
 await user.selectOptions(screen.getByLabelText('指令接收对象'),'worker:old-worker');
 await user.type(screen.getByLabelText('补充要求'),'原对象');select({...m,sessionId:'new-worker'});
 expect(screen.getByLabelText('指令接收对象')).toHaveValue('worker:old-worker');
 expect(screen.getByText('提交补充要求')).toBeDisabled();expect(api).not.toHaveBeenCalled();
});
