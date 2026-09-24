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
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var m=localStorage.getItem("ai-learn.theme")||"auto";var t=m==="auto"?(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"):m;document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme="light"}})();`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
