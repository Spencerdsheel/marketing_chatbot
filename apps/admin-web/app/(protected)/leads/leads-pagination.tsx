/**
 * 4b pagination (HANDOFF-SPEC.md §2 Tables: "pagination = bordered 8px-radius
 * page chips, active ink/white"). Prev/Next-only paging (decision 3 of
 * S13.4) doesn't give us real page numbers to enumerate, so this renders the
 * current page as the single active chip flanked by disabled-look ← / →
 * affordances that are only real links when a prior/next page exists --
 * matches the existing Prev/Next semantics exactly, just restyled.
 */
import Link from "next/link";

const chipBase =
  "grid min-h-9 min-w-9 place-items-center rounded-lg border border-[#e7e7e2] px-2.5 text-[12.5px] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#191a17]";

export function LeadsPagination({
  page,
  hasPrevious,
  hasNext,
  prevHref,
  nextHref,
  rangeLabel,
}: {
  page: number;
  hasPrevious: boolean;
  hasNext: boolean;
  prevHref: string;
  nextHref: string;
  rangeLabel: string;
}) {
  return (
    <div className="flex items-center text-[12.5px] text-[#70716a]">
      <span>{rangeLabel}</span>
      <div className="ml-auto flex gap-1.5">
        {hasPrevious ? (
          <Link href={prevHref} scroll={false} aria-label="Previous page" className={`${chipBase} text-[#45463f] hover:bg-[#f7f7f3]`}>
            ←
          </Link>
        ) : (
          <span aria-hidden className={`${chipBase} text-[#d5d5cb]`}>
            ←
          </span>
        )}
        <span aria-current="page" className={`${chipBase} border-transparent bg-[#191a17] font-semibold text-white`}>
          {page}
        </span>
        {hasNext ? (
          <Link href={nextHref} scroll={false} aria-label="Next page" className={`${chipBase} text-[#45463f] hover:bg-[#f7f7f3]`}>
            →
          </Link>
        ) : (
          <span aria-hidden className={`${chipBase} text-[#d5d5cb]`}>
            →
          </span>
        )}
      </div>
    </div>
  );
}
