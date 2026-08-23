import { useState } from "react" // QueryClient must be stable across StrictMode remounts
import { RouterProvider } from "react-router-dom" // data router created in app/router.tsx
import { QueryClientProvider } from "@tanstack/react-query" // makes useQuery/useMutation work
import { ThemeProvider } from "next-themes" // class-based light/dark for shadcn tokens + Sonner
import { TooltipProvider } from "@/components/ui/tooltip" // required by the sidebar collapsed-icon tooltips
import { Toaster } from "@/components/ui/sonner" // global toast host (used later; harmless now)
import { AuthProvider } from "@/lib/auth-provider" // session + /auth/me + login/register/logout
import { createQueryClient } from "@/lib/query-client" // default staleTime + 4xx retry skip
import { router } from "@/app/router" // Phase 3 route tree

// Root component: providers outside the router so every page can call useAuth / useQuery.
export default function App() {
  const [queryClient] = useState(createQueryClient) // one client for the life of the tab

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <AuthProvider>
            <RouterProvider router={router} />
            <Toaster />
          </AuthProvider>
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  )
}
