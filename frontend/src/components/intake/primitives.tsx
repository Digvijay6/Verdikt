/**
 * The small pieces every intake screen builds from.
 *
 * These live in `components/intake/` rather than `components/ui/` on purpose.
 * `components/ui/` is a shared surface (CLAUDE.md rule 2) that lane 3 also
 * edits, so dropping a design system into it is a coordination event. If lane 2
 * or 3 want these later we promote them deliberately, with a heads-up, rather
 * than by accident.
 */

import type { ReactNode } from "react";

/** Hard-shadowed panel. The default surface for anything grouped. */
export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <section className={`nb-card ${className}`}>{children}</section>;
}

/** A single number with its label. `attention` is for work that is stuck or
 *  waiting on a person — never for a count that is merely large. */
export function StatTile({
  value,
  label,
  tone = "plain",
}: {
  value: ReactNode;
  label: string;
  tone?: "plain" | "good" | "cool" | "attention";
}) {
  const fill = {
    plain: "bg-panel",
    good: "bg-lime",
    cool: "bg-lavender",
    attention: "bg-danger",
  }[tone];

  return (
    <div className={`nb-tile ${fill}`}>
      <b className="block text-2xl leading-tight font-extrabold tabular-nums">
        {value}
      </b>
      <span className="text-xs font-semibold text-ink/70">{label}</span>
    </div>
  );
}

/** Inline status marker. Kept to one shape so a row of them stays scannable. */
export function Pill({
  children,
  tone = "plain",
}: {
  children: ReactNode;
  tone?: "plain" | "good" | "cool" | "attention";
}) {
  const fill = {
    plain: "bg-panel",
    good: "bg-lime",
    cool: "bg-lavender",
    attention: "bg-danger",
  }[tone];

  return (
    <span
      className={`inline-block rounded-full border-2 border-ink px-2.5 py-0.5 text-xs font-bold ${fill}`}
    >
      {children}
    </span>
  );
}

/** The dark card from the reference. Used sparingly — it is the loudest thing
 *  on the page, so more than one per screen and neither stands out. */
export function InkPanel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-card border-2 border-ink bg-ink p-5 text-paper shadow-[var(--shadow-hard)] ${className}`}
    >
      {children}
    </section>
  );
}

/** Section heading with optional right-aligned controls. */
export function SectionHead({
  title,
  sub,
  actions,
}: {
  title: string;
  sub?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-3 flex flex-wrap items-baseline gap-3">
      <div className="mr-auto">
        <h2 className="mb-0">{title}</h2>
        {sub && <p className="hint m-0">{sub}</p>}
      </div>
      {actions}
    </header>
  );
}
