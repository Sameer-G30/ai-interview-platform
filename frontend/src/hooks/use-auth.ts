import { useContext } from "react" // reads the value AuthProvider put on AuthContext

import { AuthContext, type AuthContextValue } from "@/lib/auth-context" // context object only; AuthProvider lives in auth-provider.tsx

// Hook every authenticated page/guard uses; throws if a component is rendered outside AuthProvider.
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext) // null when no provider is an ancestor
  if (value === null) {
    throw new Error("useAuth must be used inside AuthProvider") // fail fast rather than returning dummy data
  }
  return value // user, tokens, login, register, logout, loading flags
}
