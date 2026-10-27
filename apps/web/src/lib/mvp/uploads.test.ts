import { expect, test } from "vitest";
import sharp from "sharp";
import { parseAssets } from "./uploads";
test("图像按内容解码，首尾帧均被保留，重复编号被拒绝",async()=>{
 const bytes=new Uint8Array(await sharp({create:{width:32,height:32,channels:3,background:"red"}}).png().toBuffer());
 const form=new FormData();form.append("first_frame",new File([bytes],"first.png"));form.append("last_frame",new File([bytes],"last.png"));
 const assets=await parseAssets(form,"h3_i2v");expect(assets.map(a=>a.key)).toEqual(["first_frame","last_frame"]);
 form.append("last_frame",new File([bytes],"again.png"));await expect(parseAssets(form,"h3_i2v")).rejects.toThrow("重复");
});
test("伪装音频和视频不会仅凭扩展名或 MIME 进入队列",async()=>{
 const form=new FormData();form.set("ref_video_0",new File(["not a video"],"fake.mp4",{type:"video/mp4"}));
 await expect(parseAssets(form,"h3_r2v")).rejects.toThrow("格式");
});
