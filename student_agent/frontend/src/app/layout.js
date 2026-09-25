import "./globals.css";

export const metadata = {
  title: "AI 学习空间 · 学生端",
  description: "面向学生的 AI 课堂学习空间",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }) {
  return (
    // 只有浅色模式，没有主题切换 —— 所以不需要首屏防闪脚本，
    // 也不需要 suppressHydrationWarning（那是为了内联脚本先于 React 改 html 属性）。
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
