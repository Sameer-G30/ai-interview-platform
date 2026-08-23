import { z } from "zod" // Zod 4 schemas drive both client-side validation and TypeScript form types

// Login form: email + password. Password min is 1 here so we do not leak the register policy on login.
export const loginSchema = z.object({
  email: z.email("enter a valid email"), // matches FastAPI EmailStr at a practical regex level
  password: z.string().min(1, "password is required").max(128, "password is too long"), // 1–128, same max as the API
})

// Type inferred from the login schema, used by useForm<LoginValues>().
export type LoginValues = z.infer<typeof loginSchema> // { email: string; password: string }

// Register form: same credentials plus optional name and a candidate/recruiter role (never admin).
export const registerSchema = z.object({
  email: z.email("enter a valid email"), // required, validated as an email
  password: z
    .string()
    .min(8, "password must be at least 8 characters") // matches RegisterRequest.password min_length=8
    .max(128, "password is too long"), // matches RegisterRequest.password max_length=128
  full_name: z.string().max(200, "name is too long").optional(), // optional; empty string is treated as omitted on submit
  role: z.enum(["candidate", "recruiter"]), // the only two values POST /auth/register accepts
})

// Type inferred from the register schema, used by useForm<RegisterValues>().
export type RegisterValues = z.infer<typeof registerSchema> // { email, password, full_name?, role }
