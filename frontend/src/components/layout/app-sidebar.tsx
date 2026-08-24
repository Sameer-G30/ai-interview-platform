import { BriefcaseIcon, FileTextIcon, LayoutDashboardIcon, LogOutIcon, MicIcon, ShieldIcon, SparklesIcon, UsersIcon } from "lucide-react" // nav + brand icons
import { NavLink } from "react-router-dom" // highlights the active sidebar item

import type { CurrentUser, UserRole } from "@/api/types" // user for footer + role to pick nav items
import { ThemeToggle } from "@/components/layout/theme-toggle" // light/dark toggle in the footer
import { Avatar, AvatarFallback } from "@/components/ui/avatar" // initials circle next to the email
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarSeparator,
} from "@/components/ui/sidebar" // shadcn sidebar primitives
import { useAuth } from "@/hooks/use-auth" // logout handler

// One sidebar row: href is omitted for "coming later" items that render disabled.
type NavItem = {
  title: string // label shown in the sidebar
  href?: string // in-app path when this phase owns a real page
  icon: React.ComponentType<{ className?: string }> // lucide icon component
  disabled?: boolean // true for placeholder items that land in later phases
  adminOnly?: boolean // true for the admin placeholder; only shown when user.isAdmin
}

// Candidate nav: overview/resume are live; matches are Phase 7; interview is later.
const candidateNav: NavItem[] = [
  { title: "Overview", href: "/candidate", icon: LayoutDashboardIcon }, // live placeholder home
  { title: "Resume", href: "/candidate/resume", icon: FileTextIcon }, // Phase 6 upload + parsed results
  { title: "Matches", href: "/candidate/matches", icon: BriefcaseIcon }, // Phase 7 ranked postings + skill gap
  { title: "Interview", icon: MicIcon, disabled: true }, // Phase 8/9
]

// Recruiter nav: overview/jobs are live; candidates/admin are later phases.
const recruiterNav: NavItem[] = [
  { title: "Overview", href: "/recruiter", icon: LayoutDashboardIcon }, // live placeholder home
  { title: "Jobs", href: "/recruiter/jobs", icon: BriefcaseIcon }, // Phase 7 posting create/list/deactivate
  { title: "Candidates", icon: UsersIcon, disabled: true }, // later recruiter work
  { title: "Admin", icon: ShieldIcon, disabled: true, adminOnly: true }, // Phase 14; shown only when is_admin
]

// Picks the nav list for the signed-in role.
function navForRole(role: UserRole): NavItem[] {
  return role === "recruiter" ? recruiterNav : candidateNav // admin is a flag on recruiter, not a third list
}

// Builds a 1–2 character fallback from the user's name or email.
function initialsFor(user: CurrentUser): string {
  const source = user.fullName?.trim() || user.email // prefer display name, fall back to email
  const parts = source.split(/[\s@._-]+/).filter(Boolean) // split on spaces and email punctuation
  const letters = parts.slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "") // first letter of up to two tokens
  return letters.join("") || "?" // never return an empty string
}

// Application sidebar: brand, role-aware nav, optional admin row, theme toggle, sign out.
export function AppSidebar() {
  const { user, logout } = useAuth() // RequireAuth guarantees user is set when this mounts

  if (!user) {
    return null // should not render outside the authenticated shell
  }

  const items = navForRole(user.role).filter((item) => !item.adminOnly || user.isAdmin) // hide Admin unless is_admin

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <div>
                <div className="flex size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                  <SparklesIcon className="size-4" />
                </div>
                <div className="flex flex-col leading-tight">
                  <span className="font-semibold">Interview Intel</span>
                  <span className="text-xs text-muted-foreground">Phase 3 shell</span>
                </div>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigate</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {items.map((item) => (
                <SidebarMenuItem key={item.title}>
                  {item.href && !item.disabled ? (
                    <SidebarMenuButton asChild tooltip={item.title}>
                      <NavLink to={item.href} end={item.href === "/candidate" || item.href === "/recruiter"}>
                        <item.icon />
                        <span>{item.title}</span>
                      </NavLink>
                    </SidebarMenuButton>
                  ) : (
                    <SidebarMenuButton disabled tooltip={`${item.title} — later phase`}>
                      <item.icon />
                      <span>{item.title}</span>
                    </SidebarMenuButton>
                  )}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarSeparator />
      <SidebarFooter>
        <div className="flex items-center gap-2 px-2 py-1">
          <Avatar className="size-8">
            <AvatarFallback>{initialsFor(user)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1 group-data-[collapsible=icon]:hidden">
            <p className="truncate text-sm font-medium">{user.fullName || user.email}</p>
            <p className="truncate text-xs text-muted-foreground">
              {user.role}
              {user.isAdmin ? " · admin" : ""}
            </p>
          </div>
          <ThemeToggle />
        </div>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              tooltip="Sign out"
              onClick={() => {
                void logout() // revoke refresh token best-effort, then RequireAuth sends the user to /login
              }}
            >
              <LogOutIcon />
              <span>Sign out</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
