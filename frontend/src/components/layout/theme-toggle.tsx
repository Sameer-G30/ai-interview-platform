import { MoonIcon, SunIcon } from "lucide-react" // icons swapped based on the resolved color scheme
import { useTheme } from "next-themes" // reads/writes the class on <html> via ThemeProvider

import { Button } from "@/components/ui/button" // shadcn button primitive

// Toggles light/dark by flipping next-themes between "light" and "dark" (system is the default on first visit).
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme() // resolvedTheme is "light" or "dark" after system is applied

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label="Toggle theme"
      onClick={() => {
        setTheme(resolvedTheme === "dark" ? "light" : "dark") // explicit light/dark so the user can override system
      }}
    >
      <SunIcon className="size-4 dark:hidden" />
      <MoonIcon className="hidden size-4 dark:block" />
    </Button>
  )
}
