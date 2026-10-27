export function GET() {
  return Response.json({ service: "comfyui-cloud-hub", status: "ok", stage: "private-studio" }, { headers: { "Cache-Control": "no-store" } });
}
