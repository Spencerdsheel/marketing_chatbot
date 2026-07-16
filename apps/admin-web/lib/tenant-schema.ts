/**
 * Shared Zod schema for the tenant-onboarding form (S13.2 decision 2).
 * Mirrors `AdminOnboardTenantRequest`
 * (services/api/src/api/admin/routes.py:36-43) field-for-field. Used by both
 * the client form (friendly inline errors) and the server action (the
 * backend remains authoritative -- this is a courtesy pre-check, not a
 * substitute for the 422s the backend can still return).
 */
import { z } from "zod";

/** Mirrors routes.py's `_SLUG_PATTERN` verbatim. */
const SLUG_PATTERN = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/;

export const onboardTenantSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Tenant name is required.")
    .max(200, "Tenant name must be 200 characters or fewer."),
  slug: z
    .string()
    .trim()
    .min(1, "Slug is required.")
    .max(63, "Slug must be 63 characters or fewer.")
    .regex(
      SLUG_PATTERN,
      "Lowercase letters, numbers, and single hyphens; must start and end alphanumeric."
    ),
  adminEmail: z
    .string()
    .trim()
    .min(3, "Admin email is required.")
    .max(254, "Admin email must be 254 characters or fewer.")
    .email("Enter a valid email."),
  adminName: z
    .string()
    .trim()
    .max(200, "Admin name must be 200 characters or fewer.")
    .optional()
    // Empty string -> omitted, so the backend receives `null`, not `""`.
    .transform((value) => (value && value.length > 0 ? value : undefined)),
  autoGeneratePassword: z.boolean(),
  // Required only when autoGeneratePassword is false -- enforced below via
  // `.superRefine` because Zod's per-field rules can't see sibling fields.
  adminPassword: z
    .string()
    .max(200, "Password must be 200 characters or fewer.")
    .optional()
    .transform((value) => (value && value.length > 0 ? value : undefined)),
});

export type OnboardTenantInput = z.input<typeof onboardTenantSchema>;

export const onboardTenantFormSchema = onboardTenantSchema.superRefine(
  (data, ctx) => {
    if (!data.autoGeneratePassword) {
      if (!data.adminPassword) {
        ctx.addIssue({
          code: "custom",
          path: ["adminPassword"],
          message: "At least 12 characters.",
        });
      } else if (data.adminPassword.length < 12) {
        ctx.addIssue({
          code: "custom",
          path: ["adminPassword"],
          message: "At least 12 characters.",
        });
      }
    }
  }
);

export type OnboardTenantParsed = z.output<typeof onboardTenantSchema>;
