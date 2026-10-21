import { SparklesIcon } from "lucide-react" // brand mark in the header
import { Outlet } from "react-router-dom" // nested page (candidate/recruiter home) renders here

import { AppSidebar } from "@/components/layout/app-sidebar" // role-aware left nav
import { ThemeToggle } from "@/components/layout/theme-toggle" // light/dark switch in the header
import { useAuth } from "@/hooks/use-auth" // role label for the header pill
import { Separator } from "@/components/ui/separator" // hairline between the trigger and the page title
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar" // shell chrome around the page

// Authenticated app chrome: collapsible sidebar, a sticky white header (brand mark, role label, theme toggle),
// and a max-width content area on the gray canvas.
export function AppShell() {
  const { user } = useAuth() // RequireAuth guarantees a user; the header shows the role
  const roleLabel = user === null || user === undefined ? "" : user.isAdmin ? "Recruiter · Admin" : user.role

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b bg-card px-4 shadow-sm">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-2 h-4" />
          <div className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <SparklesIcon className="size-4" />
          </div>
          <p className="text-sm font-semibold">Interview Intel</p>
          <span className="ml-1 rounded-full bg-accent px-2.5 py-0.5 text-xs font-medium capitalize text-accent-foreground">
            {roleLabel}
          </span>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </header>
        <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col p-4 sm:p-6">
          <Outlet />
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
