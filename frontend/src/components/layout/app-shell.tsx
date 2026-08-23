import { Outlet } from "react-router-dom" // nested page (candidate/recruiter home) renders here

import { AppSidebar } from "@/components/layout/app-sidebar" // role-aware left nav
import { Separator } from "@/components/ui/separator" // hairline between the trigger and the page title
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar" // shell chrome around the page

// Authenticated app chrome: collapsible sidebar + header with trigger + the routed page.
export function AppShell() {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-2 h-4" />
          <p className="text-sm text-muted-foreground">AI Interview Intelligence Platform</p>
        </header>
        <div className="flex flex-1 flex-col p-6">
          <Outlet />
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}
