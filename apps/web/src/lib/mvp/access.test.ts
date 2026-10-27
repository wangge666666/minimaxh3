import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { requireLocal, requireWorker, readLimited } from "./access";
beforeEach(()=>{vi.stubEnv("MVP_LOCAL_ENABLED","1");vi.stubEnv("VERCEL","");vi.stubEnv("MVP_ALLOWED_ORIGIN","https://studio.example.ts.net:8443");vi.stubEnv("MVP_WORKER_TOKEN","x".repeat(32));});
afterEach(()=>vi.unstubAllEnvs());
test("隔离端口只开放明确配置的回环来源，非法配置及跨站来源被拒绝",()=>{
 expect(()=>requireLocal(req("127.0.0.1:3100"))).toThrow();
 vi.stubEnv("MVP_LOCAL_PORT","3100");
 expect(()=>requireLocal(req("127.0.0.1:3100","http://127.0.0.1:3100","POST"))).not.toThrow();
 expect(()=>requireLocal(req("127.0.0.1:3100","http://127.0.0.1:3000","POST"))).toThrow();
 expect(()=>requireLocal(req("0.0.0.0:3100"))).toThrow();
 for(const port of ["0","65536","3100.evil"]) {vi.stubEnv("MVP_LOCAL_PORT",port);expect(()=>requireLocal(req("127.0.0.1:3000"))).toThrow("端口配置");}
});
function req(host:string,origin?:string,method="GET"){return new Request(`http://${host}/api/mvp/state`,{method,headers:{host,...(origin?{origin}:{})}});}
test("允许明确配置的私网入口，拒绝其他主机",()=>{expect(()=>requireLocal(req("studio.example.ts.net:8443","https://studio.example.ts.net:8443","POST"))).not.toThrow();expect(()=>requireLocal(req("evil.example"))).toThrow();});
test("播放器 HEAD 探测与 GET 采用相同私网主机校验",()=>{expect(()=>requireLocal(req("127.0.0.1:3000",undefined,"HEAD"))).not.toThrow();expect(()=>requireLocal(req("evil.example",undefined,"HEAD"))).toThrow();});
test("拒绝跨站提交、无来源提交及 Vercel 部署",()=>{expect(()=>requireLocal(req("127.0.0.1:3000","https://evil.example","POST"))).toThrow();expect(()=>requireLocal(req("127.0.0.1:3000",undefined,"POST"))).toThrow();vi.stubEnv("VERCEL","1");expect(()=>requireLocal(req("127.0.0.1:3000"))).toThrow();});
test("机器接口必须使用独立凭证，包括非 ASCII 错误令牌",()=>{expect(()=>requireWorker(req("127.0.0.1:3000"))).toThrow();const r=req("127.0.0.1:3000");r.headers.set("authorization",`Bearer ${"x".repeat(32)}`);expect(()=>requireWorker(r)).not.toThrow();r.headers.set("authorization",`Bearer ${"é".repeat(32)}`);expect(()=>requireWorker(r)).toThrow("凭证无效");});
test("上传流超过限制会被拒绝",async()=>{const r=new Request("http://localhost",{method:"POST",body:"12345"});await expect(readLimited(r,4)).rejects.toThrow("过大");});
test("同一私网允许默认 HTTPS 和兼容端口，但拒绝未配置来源",()=>{
 vi.stubEnv("MVP_ALLOWED_ORIGIN","https://studio.example.ts.net");
 vi.stubEnv("MVP_ALLOWED_ORIGINS","https://studio.example.ts.net:8443");
 expect(()=>requireLocal(req("studio.example.ts.net","https://studio.example.ts.net","POST"))).not.toThrow();
 expect(()=>requireLocal(req("studio.example.ts.net:8443","https://studio.example.ts.net:8443","POST"))).not.toThrow();
 expect(()=>requireLocal(req("studio.example.ts.net","https://other.example.ts.net","POST"))).toThrow();
});
