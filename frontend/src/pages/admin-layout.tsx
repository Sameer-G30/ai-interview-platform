import { NavLink, Outlet } from "react-router-dom" // tab links + nested admin pages

import { PageHeader } from "@/components/layout/page-header" // shared title block
import { useAuth } from "@/hooks/use-auth" // welcome copy; RequireAdmin already guaranteed isAdmin

// One tab under /admin. href is the in-app path; end highlights only the Users index.
type AdminTab = {
  title: string // label shown in the tab row
  href: string // /admin, /admin/postings, …
  end?: boolean // true on the Users index so /admin/postings does not stay highlighted
}

// Ops tabs: users, cross-recruiter postings, session audit, stored scores. No recruiter Interview screen.
const adminTabs: AdminTab[] = [
  { title: "Users", href: "/admin", end: true }, // PATCH is_active
  { title: "Postings", href: "/admin/postings" }, // all recruiters' jobs
  { title: "Sessions", href: "/admin/sessions" }, // practice included
  { title: "Scores", href: "/admin/scores" }, // stored composites; not recomputed
]

// Shared chrome for /admin/*: title, tab row, nested page in <Outlet />.
export function AdminLayout() {
  const { user } = useAuth() // RequireAdmin already guaranteed an is_admin recruiter

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <PageHeader
        title="Admin"
        description={`Signed in as ${user?.email ?? ""}. Manage users and postings, and review every session and score, practice included.`}
      />
      <nav className="flex flex-wrap gap-2" aria-label="Admin sections" data-testid="admin-tabs">
        {adminTabs.map((tab) => (
          <NavLink
            key={tab.href}
            to={tab.href}
            end={tab.end}
            className={({ isActive }) =>
              `rounded-full border px-4 py-1.5 text-sm font-medium transition-colors ${
                isActive
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              }`
            }
          >
            {tab.title}
          </NavLink>
        ))}
      </nav>
      {/* Nested Users / Postings / Sessions / Scores page */}
      <Outlet />
    </div>
  )
}
