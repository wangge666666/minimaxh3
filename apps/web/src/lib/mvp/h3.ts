// ComfyUI H3 uses a 32px spatial grid and 17k+5 frames at 24fps.
export const ratios = ["16:9", "9:16", "1:1"] as const;
export type Ratio = typeof ratios[number];
export const resolutions = [360, 576, 720] as const;
export const minDurationSeconds = 4;
export const maxDurationSeconds = 15;
export const minVideoFrames = 107;
export const maxVideoFrames = 362;
export function framesForDuration(seconds:number) {
  // Avoid moving to the next block due to float drift at an exact frame boundary.
  const frames=Math.ceil(seconds*24-1e-9);
  return 5+17*Math.ceil((frames-5)/17);
}
export function validVideoFrames(frames:number) {
  return Number.isInteger(frames) && frames>=minVideoFrames && frames<=maxVideoFrames && (frames-5)%17===0;
}
export function inputDurationForFrames(frames:number) {
  // Older jobs store only frames. Keep the original presets and preserve other grids.
  if(frames===124) return 5;
  if(frames===243) return 10;
  if(frames===362) return 15;
  return Math.max(4,Math.min(15,Math.floor(frames/24*10)/10));
}
export const stepOptions = [12, 20, 30] as const;
export function videoSize(ratio: Ratio, shortEdge: number) {
  const longEdge = shortEdge * 16 / 9;
  return ratio === "1:1" ? [shortEdge, shortEdge] : ratio === "16:9" ? [longEdge, shortEdge] : [shortEdge, longEdge];
}
export const videoSizes = ratios.flatMap(ratio => resolutions.map(resolution => videoSize(ratio, resolution)));
export function nativeSize(width: number, height: number) { return [Math.ceil(width / 32) * 32, Math.ceil(height / 32) * 32]; }
export function duration(frames = 124, fps = 24) { return (frames / fps).toFixed(2); }
export type AssetKind = "image" | "video" | "audio";
export type Asset = { key: string; kind: AssetKind; name: string; mime: string };
export const assetLimits = { image: 8, video: 20, audio: 10 } as const; // MiB
export const totalAssetBytes = 96 * 1024 * 1024;
export function assetKind(key: string): AssetKind | null {
  if (["reference", "first_frame", "last_frame"].includes(key) || /^ref_image_[0-8]$/.test(key)) return "image";
  if (/^ref_video_[0-2]$/.test(key)) return "video";
  if (/^ref_audio_[0-2]$/.test(key)) return "audio";
  return null;
}
export function checkAssetRoles(mode: string, assets: Pick<Asset, "key" | "kind">[]) {
  if (new Set(assets.map(a => a.key)).size !== assets.length) throw new Error("素材编号重复");
  for (const a of assets) {
    if (assetKind(a.key) !== a.kind) throw new Error("素材类型与用途不匹配");
    const valid = mode === "img2img" ? a.key === "reference" : mode === "h3_i2v" ? ["first_frame", "last_frame"].includes(a.key) : mode === "h3_r2v" ? a.key.startsWith("ref_") : false;
    if (!valid) throw new Error("当前模式不支持这种参考素材");
  }
  if (mode === "img2img" && !assets.some(a => a.key === "reference")) throw new Error("请上传参考图片");
  if (mode === "h3_i2v" && !assets.some(a => a.key === "first_frame")) throw new Error("请上传首帧图片");
  if (mode === "h3_r2v" && !assets.length) throw new Error("请至少上传一项参考素材");
  for (const prefix of ["ref_image_", "ref_video_", "ref_audio_"]) {
    const keys = assets.filter(a => a.key.startsWith(prefix)).map(a => Number(a.key.slice(prefix.length))).sort((a,b) => a-b);
    if (keys.some((value, index) => value !== index)) throw new Error("参考素材编号必须连续");
  }
}
