export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="px-2 py-3 text-center">
      <p className="text-xs text-muted-foreground">© {currentYear} AI 教育平台</p>
    </footer>
  )
}
