import {render,screen} from "@testing-library/react";
import {it,expect,vi} from "vitest";
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
