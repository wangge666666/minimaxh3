import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "私人创作室 · MiniMax H3", description: "通过私网生成视频和图片的个人工作台" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="zh-CN"><body>{children}</body></html>; }
