import type { ReactNode } from "react" // description and actions can be rich content

// Shared page title block: one h1, an optional description, and an optional right-aligned action slot.
export function PageHeader({
  title, // the page's h1 text (smoke tests find pages by this text)
  description, // one short sentence under the title
  actions, // buttons or links shown to the right on wide screens
}: {
  title: string // h1 text
  description?: ReactNode // optional supporting copy
  actions?: ReactNode // optional action slot
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description !== undefined ? <p className="text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions !== undefined ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  )
}
