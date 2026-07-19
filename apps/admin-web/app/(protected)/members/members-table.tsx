"use client";

/**
 * Members table (7b), restyled to spec: header row #f7f7f3 uppercase muted,
 * rows 13px with `border-faint` dividers, avatar initials chip, role badge
 * (real 2-role mapping via `roleBadgeStyle`). Open-lead-load column is
 * omitted (see `page.tsx` header comment) -- columns are MEMBER / ROLE /
 * LAST ACTIVE / actions.
 *
 * The active/inactive toggle requires confirmation before deactivating
 * (accessibility instructions: a destructive-ish action affecting someone's
 * access). Reactivating (a non-destructive action) does not require
 * confirmation.
 */
import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { MemberSummary } from "@/lib/members";
import { formatLastActive, initialsFromMember, roleBadgeStyle } from "@/lib/members-presentation";
import { toggleMemberActiveAction } from "@/app/(protected)/members/actions";

function RoleBadge({ role }: { role: string }) {
  const style = roleBadgeStyle(role);
  return (
    <span
      className="rounded-full px-[9px] py-[3px] text-[10.5px] font-bold"
      style={{ background: style.bg, color: style.fg }}
    >
      {style.label}
    </span>
  );
}

function Avatar({ member }: { member: MemberSummary }) {
  const initials = initialsFromMember(member.name, member.email);
  const isAdmin = member.role === "CLIENT_ADMIN";
  return (
    <span
      className="flex h-8 w-8 flex-none items-center justify-center rounded-full text-[10.5px] font-bold"
      style={
        isAdmin
          ? { background: "#191a17", color: "#e4f222" }
          : { background: "#dcdcd2", color: "#5a5b54" }
      }
      aria-hidden="true"
    >
      {initials}
    </span>
  );
}

function DeactivateConfirmDialog({
  member,
  onConfirm,
  onCancel,
  pending,
}: {
  member: MemberSummary;
  onConfirm: () => void;
  onCancel: () => void;
  pending: boolean;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="deactivate-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="flex w-full max-w-sm flex-col gap-4 rounded-2xl border border-[#e7e7e2] bg-white p-5 shadow-xl">
        <div>
          <h2 id="deactivate-dialog-title" className="text-[15px] font-bold text-[#191a17]">
            Deactivate {member.name ?? member.email}?
          </h2>
          <p className="mt-1.5 text-[13px] text-[#45463f]">
            They will immediately lose access to this tenant&apos;s console. You can reactivate
            them at any time.
          </p>
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onCancel} disabled={pending}>
            Cancel
          </Button>
          <Button type="button" variant="destructive" onClick={onConfirm} disabled={pending}>
            {pending ? "Deactivating…" : "Deactivate"}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function MembersTable({ members }: { members: MemberSummary[] }) {
  const [rows, setRows] = useState(members);
  const [confirmTarget, setConfirmTarget] = useState<MemberSummary | null>(null);
  const [errorByMember, setErrorByMember] = useState<Record<string, string>>({});
  const [isPending, startTransition] = useTransition();

  function applyToggle(userId: string, active: boolean) {
    setErrorByMember((prev) => {
      const next = { ...prev };
      delete next[userId];
      return next;
    });
    startTransition(async () => {
      const result = await toggleMemberActiveAction(userId, active);
      if (result.status === "ok" && result.member) {
        const updated = result.member;
        setRows((prev) => prev.map((m) => (m.id === userId ? updated : m)));
      } else {
        setErrorByMember((prev) => ({
          ...prev,
          [userId]: result.message ?? "Something went wrong.",
        }));
      }
    });
  }

  function handleToggleClick(member: MemberSummary) {
    if (member.active) {
      // Destructive-ish: confirm before deactivating.
      setConfirmTarget(member);
    } else {
      applyToggle(member.id, true);
    }
  }

  if (rows.length === 0) {
    return (
      <div className="rounded-[14px] border border-[#e7e7e2] p-8 text-center text-[13px] text-[#70716a]">
        No team members yet.
      </div>
    );
  }

  return (
    <>
      <div className="overflow-hidden rounded-[14px] border border-[#e7e7e2]">
        <Table>
          <TableHeader>
            <TableRow className="border-b border-[#e7e7e2] bg-[#f7f7f3] hover:bg-[#f7f7f3]">
              <TableHead className="h-auto py-[11px] pl-4 text-[11.5px] font-semibold text-[#70716a] uppercase">
                Member
              </TableHead>
              <TableHead className="h-auto py-[11px] text-[11.5px] font-semibold text-[#70716a] uppercase">
                Role
              </TableHead>
              <TableHead className="h-auto py-[11px] text-[11.5px] font-semibold text-[#70716a] uppercase">
                Last active
              </TableHead>
              <TableHead className="h-auto py-[11px] text-[11.5px] font-semibold text-[#70716a] uppercase">
                Status
              </TableHead>
              <TableHead className="h-auto py-[11px] pr-4 text-right text-[11.5px] font-semibold text-[#70716a] uppercase">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((member) => (
              <TableRow key={member.id} className="border-b border-[#f0f0ea] last:border-0">
                <TableCell className="py-[13px] pl-4">
                  <div className="flex items-center gap-2.5">
                    <Avatar member={member} />
                    <div>
                      <div className="text-[13px] font-bold text-[#191a17]">
                        {member.name ?? member.email}
                      </div>
                      <div className="text-[11px] text-[#96978e]">{member.email}</div>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="py-[13px]">
                  <RoleBadge role={member.role} />
                </TableCell>
                <TableCell className="py-[13px] text-[#70716a]">
                  {formatLastActive(member.lastLoginAt)}
                </TableCell>
                <TableCell className="py-[13px]">
                  <span
                    className={
                      member.active
                        ? "rounded-full bg-[#dcefdc] px-2.5 py-1 text-[11px] font-semibold text-[#1f6a2f]"
                        : "rounded-full bg-[#f6e3df] px-2.5 py-1 text-[11px] font-semibold text-[#c2452d]"
                    }
                  >
                    {member.active ? "Active" : "Inactive"}
                  </span>
                  {errorByMember[member.id] ? (
                    <p role="alert" className="mt-1 text-[11px] text-[#c2452d]">
                      {errorByMember[member.id]}
                    </p>
                  ) : null}
                </TableCell>
                <TableCell className="py-[13px] pr-4 text-right">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="min-h-[36px] min-w-[44px]"
                    disabled={isPending}
                    onClick={() => handleToggleClick(member)}
                  >
                    {member.active ? "Deactivate" : "Activate"}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {confirmTarget ? (
        <DeactivateConfirmDialog
          member={confirmTarget}
          pending={isPending}
          onCancel={() => setConfirmTarget(null)}
          onConfirm={() => {
            applyToggle(confirmTarget.id, false);
            setConfirmTarget(null);
          }}
        />
      ) : null}
    </>
  );
}
