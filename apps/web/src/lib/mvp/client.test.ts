import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiError, api, submitWithRecovery, uploadIdleMs, uploadJob, uploadTimeoutMs } from "./client";
const requestId="00000000-0000-4000-8000-000000000001";
const accepted={id:"accepted-job",requestId,status:"queued"};
const form=()=>{const f=new FormData();f.set("params",JSON.stringify({requestId}));return f;};
class FakeXHR {
  static last:FakeXHR;
  upload:{onprogress:((e:{loaded:number;total:number;lengthComputable:boolean})=>void)|null;onload:(()=>void)|null}={onprogress:null,onload:null};
  onload:(()=>void)|null=null;onerror:(()=>void)|null=null;ontimeout:(()=>void)|null=null;onabort:(()=>void)|null=null;onprogress:(()=>void)|null=null;
  timeout=0;status=201;responseText=JSON.stringify(accepted);
  open=vi.fn();setRequestHeader=vi.fn();send=vi.fn();
  abort=vi.fn(()=>this.onabort?.());
  constructor(){FakeXHR.last=this;}
}
beforeEach(()=>{vi.useFakeTimers();vi.stubGlobal("XMLHttpRequest",FakeXHR);});
afterEach(()=>{vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();vi.restoreAllMocks();});
test("持续有进度的上传超过旧的两分钟限制仍可成功",async()=>{
 const progress=vi.fn();const pending=uploadJob(form(),progress);const xhr=FakeXHR.last;
 expect(xhr.timeout).toBe(uploadTimeoutMs);expect(xhr.setRequestHeader).toHaveBeenCalledWith("X-Request-Id",requestId);
 for(let i=1;i<=3;i++){vi.advanceTimersByTime(60000);xhr.upload.onprogress?.({loaded:i*100,total:400,lengthComputable:true});}
 expect(xhr.abort).not.toHaveBeenCalled();expect(progress).toHaveBeenLastCalledWith({phase:"uploading",loaded:300,total:400});
 xhr.upload.onload?.();expect(progress).toHaveBeenLastCalledWith({phase:"validating",loaded:400,total:400});
 xhr.onload?.();expect((await pending).id).toBe("accepted-job");expect(vi.getTimerCount()).toBe(0);
});
test("停滞上传给出可读错误，并清理计时器",async()=>{
 const pending=uploadJob(form(),vi.fn());const assertion=expect(pending).rejects.toThrow("连续 90 秒没有响应");
 vi.advanceTimersByTime(uploadIdleMs);await assertion;expect(FakeXHR.last.abort).toHaveBeenCalledOnce();expect(vi.getTimerCount()).toBe(0);
});
test("响应丢失后按提交编号找回任务，不再上传或生成",async()=>{
 const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(accepted)));vi.stubGlobal("fetch",fetch);
 const progress=vi.fn(),pending=submitWithRecovery(form(),progress);FakeXHR.last.onerror?.();
 expect((await pending).id).toBe("accepted-job");expect(fetch).toHaveBeenCalledWith(`/api/mvp/jobs/request/${requestId}`,expect.anything());expect(FakeXHR.last.send).toHaveBeenCalledOnce();
 expect(progress).toHaveBeenLastCalledWith({phase:"checking",loaded:0,total:0});
});
test("用户重试先查询，已创建的任务不会重复传素材",async()=>{
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify(accepted))));
 const previous=FakeXHR.last;expect((await submitWithRecovery(form(),vi.fn(),true)).id).toBe("accepted-job");expect(FakeXHR.last).toBe(previous);
});
test("明确的文件校验失败直接显示服务端原因",async()=>{
 const fetch=vi.fn();vi.stubGlobal("fetch",fetch);
 const pending=submitWithRecovery(form(),vi.fn());FakeXHR.last.status=413;FakeXHR.last.responseText=JSON.stringify({error:"图片最大 8 MB"});FakeXHR.last.onload?.();
 await expect(pending).rejects.toThrow("图片最大 8 MB");expect(fetch).not.toHaveBeenCalled();
});
test("网络中断且无法确认时保留原错误和防重复提示",async()=>{
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify({error:"未创建"}),{status:404})));
 const pending=submitWithRecovery(form(),vi.fn());FakeXHR.last.ontimeout?.();
 await expect(pending).rejects.toThrow("沿用本次提交编号");
});
test("状态轮询超时及代理非 JSON 响应不暴露原始异常",async()=>{
 vi.stubGlobal("fetch",vi.fn().mockRejectedValue(new DOMException("signal timed out","TimeoutError")));
 await expect(api("/api/mvp/state")).rejects.toThrow("连接暂时超时");
 vi.stubGlobal("fetch",vi.fn().mockImplementation(()=>Promise.resolve(new Response("<html>gateway timeout</html>",{status:504}))));
 await expect(api("/api/mvp/state")).rejects.toEqual(expect.objectContaining({status:504}));
 await expect(api("/api/mvp/state")).rejects.toBeInstanceOf(ApiError);
});
