import { expect, test } from "vitest";
import { randomUUID } from "node:crypto";
import { createSchema } from "./schema";
import { checkAssetRoles, framesForDuration, inputDurationForFrames, nativeSize, videoSizes } from "./h3";
const base={requestId:randomUUID(),mode:"h3_t2v",prompt:"a landscape",width:640,height:360,seed:1,denoise:1};
test("三种比例和三档尺寸都可提交；非法尺寸、时长和帧率被拒绝",()=>{
 for(const [width,height] of videoSizes) expect(createSchema.safeParse({...base,width,height,frames:243,steps:30}).success).toBe(true);
 for(const extra of [{width:999,height:777},{frames:120},{frames:1000},{fps:30},{steps:999}]) expect(createSchema.safeParse({...base,...extra}).success).toBe(false);
 expect(nativeSize(1280,720)).toEqual([1280,736]);
});
test("模式、素材数量、连续编号和首帧约束均在服务端验证",()=>{
 expect(()=>checkAssetRoles("h3_r2v",[{key:"ref_video_0",kind:"video"},{key:"ref_audio_0",kind:"audio"}])).not.toThrow();
 for(const assets of [[{key:"ref_image_9",kind:"image"}],[{key:"ref_video_1",kind:"video"}],[{key:"ref_audio_0",kind:"image"}]] as const) expect(()=>checkAssetRoles("h3_r2v",[...assets])).toThrow();
 expect(()=>checkAssetRoles("h3_i2v",[{key:"last_frame",kind:"image"}])).toThrow("首帧");
 expect(()=>checkAssetRoles("h3_t2v",[{key:"ref_audio_0",kind:"audio"}])).toThrow("不支持");
});

test.each([[4,107],[4.35,107],[5,124],[5.17,141],[6,158],[7,175],[7.5,192],[8,192],[9,226],[10,243],[11,277],[12,294],[13,328],[14,345],[15,362]])("%s 秒请求对齐为 %s 帧，保留原始请求时长",(durationSeconds,frames)=>{
 expect(framesForDuration(durationSeconds)).toBe(frames);
 const parsed=createSchema.parse({...base,durationSeconds,frames});
 expect(parsed.durationSeconds).toBe(durationSeconds);
});

test("网格边界不因浮点误差跳到下一档；旧任务可复用",()=>{
 for(let frames=107;frames<=362;frames+=17) {
  expect(framesForDuration(frames/24)).toBe(frames);
  expect(framesForDuration(frames/24+0.0001)).toBe(frames+17);
  expect(framesForDuration(frames/24-0.0001)).toBe(frames);
  const seconds=inputDurationForFrames(frames);
  expect(seconds).toBeGreaterThanOrEqual(4);expect(seconds).toBeLessThanOrEqual(15);
  expect(framesForDuration(seconds)).toBe(frames);
 }
 expect([124,243,362].map(inputDurationForFrames)).toEqual([5,10,15]);
});

test.each([{durationSeconds:3.99,frames:107},{durationSeconds:15.01,frames:362},{durationSeconds:6,frames:124},{durationSeconds:6},{durationSeconds:"6",frames:158},{durationSeconds:Number.NaN,frames:158},{durationSeconds:Infinity,frames:158},{frames:106},{frames:363},{frames:158.5}])("拒绝非法时长、越界或不匹配的帧数：%j",extra=>{
 expect(createSchema.safeParse({...base,...extra}).success).toBe(false);
});
