interface PillProps {
  tone: string
  children: React.ReactNode
  dot?: boolean
}

export function Pill({ tone, children, dot = false }: PillProps) {
  return (
    <span className={`pill ${tone}`}>
      {dot && <span className="dot" />}
      {children}
    </span>
  )
}
