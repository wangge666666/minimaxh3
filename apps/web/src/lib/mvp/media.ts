import { StoreError } from "./store";

export function validateMp4(data: Uint8Array) {
  const bytes=Buffer.from(data);let offset=0;const types=new Set<string>();
  while(offset<bytes.length) {
    if(offset+8>bytes.length) throw new StoreError("MP4 文件不完整",400);
    let size=bytes.readUInt32BE(offset);let header=8;
    const type=bytes.toString("ascii",offset+4,offset+8);
    if(size===1) { if(offset+16>bytes.length) throw new StoreError("MP4 文件不完整",400);const wide=bytes.readBigUInt64BE(offset+8);if(wide>BigInt(Number.MAX_SAFE_INTEGER)) throw new StoreError("MP4 长度无效",400);size=Number(wide);header=16; }
    if(size===0) size=bytes.length-offset;
    if(size<header||offset+size>bytes.length) throw new StoreError("MP4 文件长度无效",400);
    if(type==="ftyp" && size<header+8) throw new StoreError("MP4 格式无效",400);
    if(type==="mdat" && size===header) throw new StoreError("MP4 缺少媒体数据",400);
    types.add(type);offset+=size;
  }
  if(!["ftyp","moov","mdat"].every(t=>types.has(t))) throw new StoreError("结果不是完整的 MP4",400);
}
type ByteSource = { length: number; read: (start: number, end: number) => Uint8Array };
export function mediaResponse(data:Uint8Array|ByteSource,mime:string,id:string,request:Request) {
  const download=new URL(request.url).searchParams.has("download");
  // Completed job results are immutable and UUID-addressed. Cache only on this device.
  const etag=`"hub-${id}-${data.length}"`;
  const extension=mime==="video/mp4"?"mp4":mime==="image/jpeg"?"jpg":"png";
  const headers:Record<string,string>={"Content-Type":mime,"Cache-Control":"private, max-age=86400, immutable","ETag":etag,"Content-Disposition":`${download?"attachment":"inline"}; filename="${id}.${extension}"`,"X-Content-Type-Options":"nosniff","Accept-Ranges":"bytes"};
  const matches=request.headers.get("if-none-match")?.split(",").some(value=>value.trim()==="*" || value.trim().replace(/^W\//,"")===etag);
  if(matches) return new Response(null,{status:304,headers});
  if(request.method==="HEAD") return new Response(null,{headers:{...headers,"Content-Length":String(data.length)}});
  const ifRange=request.headers.get("if-range");
  const range=download || (ifRange && ifRange!==etag)?null:request.headers.get("range");let start=0,end=data.length-1,status=200;
  if(range) {
    const match=/^bytes=(\d*)-(\d*)$/.exec(range);
    if(!match||(!match[1]&&!match[2])) return new Response(null,{status:416,headers:{...headers,"Content-Range":`bytes */${data.length}`}});
    if(!match[1]) start=Math.max(0,data.length-Number(match[2]));
    else {start=Number(match[1]);if(match[2])end=Math.min(end,Number(match[2]));}
    if(start>end||start>=data.length||!Number.isSafeInteger(start)||!Number.isSafeInteger(end)) return new Response(null,{status:416,headers:{...headers,"Content-Range":`bytes */${data.length}`}});
    status=206;headers["Content-Range"]=`bytes ${start}-${end}/${data.length}`;
  }
  headers["Content-Length"]=String(end-start+1);
  const bytes=data instanceof Uint8Array?data.subarray(start,end+1):data.read(start,end);
  return new Response(new Uint8Array(bytes),{status,headers});
}
