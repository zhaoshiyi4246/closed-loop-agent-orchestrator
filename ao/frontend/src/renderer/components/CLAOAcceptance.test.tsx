import {cleanup,render,screen} from "@testing-library/react";
import {afterEach,it,expect,vi} from "vitest";
import {CLAOAcceptance} from "./CLAOAcceptance";
const { mission }=vi.hoisted(()=>({mission:{request:{id:"old-mission",projectId:"p",objective:"old objective",agent:"opencode",model:"old-model",criteria:[]},state:"DONE",reason:"recorded acceptance",sessionId:"old-worker",verifierSessionId:"old-review",evidence:[],operations:[],revision:1}}));
vi.mock("@tanstack/react-query",()=>({useQuery:()=>({data:{missions:[mission]},isError:false}),useQueryClient:()=>({})}));
vi.mock("@tanstack/react-router",()=>({useNavigate:()=>vi.fn()}));
it("does not turn missing legacy role history into never-called",()=>{
 render(<CLAOAcceptance sessionId="old-worker"/>);
 expect(screen.getByText("历史已记录 Verifier Session，未提供角色调用明细")).toBeInTheDocument();
 expect(screen.queryByText("未调用")).not.toBeInTheDocument();
 expect(screen.getByText("old objective")).toBeInTheDocument();
});
afterEach(cleanup);
it("child session opens one parent overview with its final acceptance",()=>{
 const child={...mission,request:{...mission.request,id:"child",objective:"子任务"},sessionId:"child-worker",coordinatorId:"old-mission",verifierSessionId:undefined};
 Object.assign(mission,{state:"FAILED",subtasks:[child]});
 render(<CLAOAcceptance sessionId="child-worker"/>);
 expect(screen.getByText("CLAO · 验收未通过")).toBeInTheDocument();
 expect(screen.getAllByTestId("clao-run-view")).toHaveLength(1);
 expect(screen.getByText("old objective")).toBeInTheDocument();
});
