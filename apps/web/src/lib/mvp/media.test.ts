import { expect, test, vi } from "vitest";
import { validateMp4, mediaResponse } from "./media";
import { createSchema } from "./schema";
const request=(range?:string)=>new Request("http://localhost/media",{headers:range?{range}:{}});
test("拒绝不完整或伪装的 MP4",()=>{expect(()=>validateMp4(new Uint8Array([1,2,3]))).toThrow();const ftyp=Buffer.alloc(24);ftyp.writeUInt32BE(24);ftyp.write("ftyp",4);expect(()=>validateMp4(ftyp)).toThrow("完整");});
test("视频范围请求返回正确字节，错误范围返回 416",async()=>{const bytes=new Uint8Array([10,11,12,13,14]);const partial=mediaResponse(bytes,"video/mp4","job",request("bytes=1-3"));expect(partial.status).toBe(206);expect(partial.headers.get("content-range")).toBe("bytes 1-3/5");expect([...new Uint8Array(await partial.arrayBuffer())]).toEqual([11,12,13]);expect(mediaResponse(bytes,"video/mp4","job",request("bytes=999-")).status).toBe(416);expect(mediaResponse(bytes,"video/mp4","job",request("bytes=0-1,3-4")).status).toBe(416);});
test("尾部范围和下载类型正确",async()=>{const bytes=new Uint8Array([1,2,3]);const tail=mediaResponse(bytes,"video/mp4","job",request("bytes=-1"));expect([...new Uint8Array(await tail.arrayBuffer())]).toEqual([3]);const download=mediaResponse(bytes,"video/mp4","job",new Request("http://localhost/media?download=1"));expect(download.headers.get("content-disposition")).toContain('attachment; filename="job.mp4"');expect(download.headers.get("content-type")).toBe("video/mp4");});
test("H3 参数拒绝未开放的尺寸、帧数和帧率",()=>{const p={requestId:"00000000-0000-4000-8000-000000000001",mode:"h3_t2v",prompt:"a lake",width:640,height:384,seed:42,denoise:0.6,frames:124,fps:24};expect(createSchema.safeParse(p).success).toBe(true);for(const override of [{width:768},{frames:1000},{fps:60}])expect(createSchema.safeParse({...p,...override}).success).toBe(false);});
test("HEAD 与缓存命中不读取 BLOB，Range 只读取请求片段",async()=>{
 const read=vi.fn(()=>new Uint8Array([3,4]));const source={length:1000000,read};
 const head=mediaResponse(source,"video/mp4","fixed",new Request("http://localhost/media",{method:"HEAD"}));
 expect(head.status).toBe(200);expect(head.headers.get("content-length")).toBe("1000000");expect(await head.text()).toBe("");expect(read).not.toHaveBeenCalled();
 expect(head.headers.get("cache-control")).toContain("private");expect(head.headers.get("cache-control")).not.toContain("public");
 const etag=head.headers.get("etag")!;
 const cached=mediaResponse(source,"video/mp4","fixed",new Request("http://localhost/media",{headers:{"If-None-Match":etag}}));expect(cached.status).toBe(304);expect(read).not.toHaveBeenCalled();
 const range=mediaResponse(source,"video/mp4","fixed",new Request("http://localhost/media",{headers:{Range:"bytes=3-4","If-Range":etag}}));expect(range.status).toBe(206);expect(read).toHaveBeenCalledWith(3,4);expect([...new Uint8Array(await range.arrayBuffer())]).toEqual([3,4]);
});
test("过期的 If-Range 返回完整结果，封面使用 JPEG 类型",async()=>{
 const bytes=new Uint8Array([1,2,3]);const response=mediaResponse(bytes,"image/jpeg","cover",new Request("http://localhost/media",{headers:{Range:"bytes=1-2","If-Range":'"old-version"'}}));
 expect(response.status).toBe(200);expect([...new Uint8Array(await response.arrayBuffer())]).toEqual([1,2,3]);expect(response.headers.get("content-disposition")).toContain("cover.jpg");
});
