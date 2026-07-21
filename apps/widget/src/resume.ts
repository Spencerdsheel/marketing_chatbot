/**
 * Resume-record read/write helper (SR-3 decision 1-5, scope item 1).
 *
 * Opt-in, tab-scoped conversation continuity: when a tenant has
 * `resume_enabled` on, the widget persists the already-minted visitor
 * bearer token + its `conversation_id` into `sessionStorage` (NEVER
 * `localStorage`, NEVER a cookie -- decision 3) under one namespaced key, so
 * a reload/same-tab navigation can reuse the still-valid token instead of
 * minting a fresh one, and continue the same conversation.
 *
 * Decision 4 (PII minimization -- MANDATORY): the stored record contains
 * ONLY `{token, expiresAt, conversationId, lastActive}`. Never `tenant_id`
 * (it lives inside the signed token, never separately stored), never
 * name/email/phone, never message content.
 *
 * Decision 5 (TTL): a record is considered valid only when BOTH
 * `now - lastActive <= 15 min` (inactivity ceiling) AND `now < expiresAt`
 * (the token's own absolute ceiling, from `/widget/session`) hold. Either
 * violated -> the record is discarded (removed from storage) and `null` is
 * returned -- the caller falls back to the standard S14.1 mint-fresh boot.
 *
 * Decision 7 (no silent fallback / never throws): every function here is
 * defensive against a corrupt stored value, a Zod-validation failure, or an
 * unavailable `sessionStorage` (private-mode/quota/security-restricted
 * embed) -- none of that may ever throw into boot. `writeResumeRecord` and
 * `touchResumeRecord` degrade to a silent no-op (+ `console.debug`);
 * `readResumeRecord` degrades to `null`.
 */
import { z } from "zod";

/** Namespaced so this can never collide with a host page's own keys and is
 * trivially greppable/inspectable in devtools (decision 3). */
export const RESUME_KEY = "cw:resume:v1";

/** 15-minute inactivity ceiling (decision 5 / Open question 3, locked). */
export const TTL_MS = 15 * 60 * 1000;

const ResumeRecordSchema = z.object({
  token: z.string().min(1),
  expiresAt: z.string().min(1),
  conversationId: z.string().min(1).nullable(),
  lastActive: z.string().min(1),
});

export interface ResumeRecord {
  /** The already-minted visitor bearer token -- reused, never re-derived. */
  token: string;
  /** The token's own 30-min ceiling (ISO-8601), from `/widget/session`. */
  expiresAt: string;
  /** The thread to resume; `null` before the first turn. */
  conversationId: string | null;
  /** ISO-8601; refreshed on each successful turn -- drives the inactivity TTL. */
  lastActive: string;
}

/** Safe accessor -- `sessionStorage` itself can throw synchronously (private
 * mode, embed-restricted iframe, quota) even before `.getItem`/`.setItem`
 * runs. Returns `null` on any access failure, never throws. */
function tryGetSessionStorage(): Storage | null {
  try {
    return sessionStorage;
  } catch {
    return null;
  }
}

/**
 * Read the resume record, honoring the dual TTL (decision 5). Returns the
 * validated record only when unexpired; otherwise removes the stored key
 * (if present) and returns `null`. Never throws.
 */
export function readResumeRecord(now: Date): ResumeRecord | null {
  const storage = tryGetSessionStorage();
  if (!storage) return null;

  let raw: string | null;
  try {
    raw = storage.getItem(RESUME_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(raw);
  } catch {
    clearResumeRecord();
    return null;
  }

  const parsed = ResumeRecordSchema.safeParse(parsedJson);
  if (!parsed.success) {
    clearResumeRecord();
    return null;
  }

  const record = parsed.data;
  const lastActiveMs = Date.parse(record.lastActive);
  const expiresAtMs = Date.parse(record.expiresAt);
  if (!Number.isFinite(lastActiveMs) || !Number.isFinite(expiresAtMs)) {
    clearResumeRecord();
    return null;
  }

  const nowMs = now.getTime();
  const inactiveTooLong = nowMs - lastActiveMs > TTL_MS;
  const tokenExpired = nowMs >= expiresAtMs;
  if (inactiveTooLong || tokenExpired) {
    clearResumeRecord();
    return null;
  }

  return record;
}

/**
 * Persist the resume record. No-op-safe if `sessionStorage` is unavailable
 * (private-mode/quota/restricted embed) -- swallows the failure and
 * `console.debug`s, never throws into boot (decision 7).
 */
export function writeResumeRecord(record: ResumeRecord): void {
  const storage = tryGetSessionStorage();
  if (!storage) {
    console.debug("[chatbot-widget] resume: sessionStorage unavailable, skipping persist.");
    return;
  }
  try {
    storage.setItem(RESUME_KEY, JSON.stringify(record));
  } catch {
    console.debug("[chatbot-widget] resume: sessionStorage.setItem failed, skipping persist.");
  }
}

/**
 * Update `lastActive` (+ `conversationId`, when newly known) after a
 * successful turn. A no-op when no record currently exists -- never
 * fabricates one (that would require also knowing `token`/`expiresAt`,
 * which this function is not given).
 */
export function touchResumeRecord(conversationId: string | null, now: Date): void {
  const storage = tryGetSessionStorage();
  if (!storage) return;

  let raw: string | null;
  try {
    raw = storage.getItem(RESUME_KEY);
  } catch {
    return;
  }
  if (!raw) return;

  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(raw);
  } catch {
    return;
  }

  const parsed = ResumeRecordSchema.safeParse(parsedJson);
  if (!parsed.success) return;

  const updated: ResumeRecord = {
    ...parsed.data,
    conversationId: conversationId ?? parsed.data.conversationId,
    lastActive: now.toISOString(),
  };
  writeResumeRecord(updated);
}

/** Remove the stored record (used on RESUME_REJECTED, decision 7). Safe no-op if absent/unavailable. */
export function clearResumeRecord(): void {
  const storage = tryGetSessionStorage();
  if (!storage) return;
  try {
    storage.removeItem(RESUME_KEY);
  } catch {
    // Best-effort cleanup only -- never throw into boot/turn handling.
  }
}
