import { clsx, type ClassValue } from "clsx" // builds a className string from mixed truthy/falsy/object/array inputs
import { twMerge } from "tailwind-merge" // drops conflicting Tailwind classes so the last one wins

// Merges optional class names and resolves Tailwind conflicts (e.g. `p-2` vs `p-4`).
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs)) // clsx concatenates; twMerge then de-duplicates Tailwind utilities
}
