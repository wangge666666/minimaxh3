import sharp from "sharp";
import { assetKind, assetLimits, checkAssetRoles, totalAssetBytes } from "./h3";
import { StoreError, type StoredAsset } from "./store";

function containerMime(kind: string, bytes: Uint8Array) {
  const b=Buffer.from(bytes);
  if (kind==="video") {
    if (b.toString("ascii",4,8)==="ftyp") return "video/mp4";
    if (b.subarray(0,4).equals(Buffer.from([0x1a,0x45,0xdf,0xa3]))) return "video/webm";
  }
  if (kind==="audio") {
    if(b.toString("ascii",0,4)==="RIFF" && b.toString("ascii",8,12)==="WAVE") return "audio/wav";
    if(b.toString("ascii",0,3)==="ID3" || (b[0]===0xff && (b[1]&0xe0)===0xe0)) return "audio/mpeg";
    if(b.toString("ascii",0,4)==="fLaC") return "audio/flac";
    if(b.toString("ascii",0,4)==="OggS") return "audio/ogg";
    if(b.toString("ascii",4,8)==="ftyp") return "audio/mp4";
  }
  throw new StoreError("素材文件格式不支持，请使用页面列出的格式",400);
}
export async function parseAssets(form: FormData, mode: string): Promise<StoredAsset[]> {
  const assets: StoredAsset[]=[];
  let total=0;
  for (const [rawKey,file] of form) {
    if (rawKey==="params") continue;
    let key=rawKey;
    if(key==="reference" && mode==="h3_i2v") key="first_frame";
    if(key==="reference" && mode==="h3_r2v") key="ref_image_0";
    const kind=assetKind(key);
    if(!kind || !(file instanceof File) || !file.size) throw new StoreError("参考素材字段或文件无效",400);
    total+=file.size;
    if(total>totalAssetBytes || file.size>assetLimits[kind]*1024*1024) throw new StoreError(`素材过大：图片 8 MB、视频 20 MB、音频 10 MB，总计不超过 96 MB`,413);
    let bytes=new Uint8Array(await file.arrayBuffer()),mime="image/png";
    if(kind==="image") {
      const image=sharp(bytes,{limitInputPixels:16000000,animated:false});
      const meta=await image.metadata();
      if(!["png","jpeg","webp"].includes(meta.format??"") || (meta.pages??1)>1) throw new StoreError("只支持静态 PNG、JPEG、WebP 图片",400);
      bytes=new Uint8Array(await image.rotate().resize({width:2048,height:2048,fit:"inside",withoutEnlargement:true}).png().toBuffer());
    } else mime=containerMime(kind,bytes);
    assets.push({key,kind,name:file.name.replace(/[\\/\u0000-\u001f]/g,"_").slice(0,120),mime,data:bytes});
  }
  try { checkAssetRoles(mode,assets); } catch (e) { throw new StoreError((e as Error).message,400); }
  return assets;
}
