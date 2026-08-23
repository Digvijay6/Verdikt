/**
 * Top navigation with a sliding indicator.
 *
 * The pill is a single element rendered inside whichever item is active, and
 * `layoutId` makes Motion animate it between positions on its own. No refs, no
 * offsetLeft/offsetWidth measuring, no resize listener — the alternative
 * implementations of this all end up recalculating on font load and window
 * resize, and getting one of those wrong is how the indicator ends up sitting
 * half an item off.
 */

import { motion } from "motion/react";
import { NavLink, useLocation } from "react-router-dom";

export type NavItem = { to: string; label: string };

export function MagicNav({ items }: { items: NavItem[] }) {
  const { pathname } = useLocation();

  // Longest matching prefix, so /applications/abc still lights "Candidates"
  // rather than nothing.
  const active = items
    .filter((i) => pathname === i.to || pathname.startsWith(i.to + "/"))
    .sort((a, b) => b.to.length - a.to.length)[0];

  return (
    <nav className="flex items-center gap-1" aria-label="Main">
      {items.map((item) => {
        const isActive = item === active;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            aria-current={isActive ? "page" : undefined}
            className="relative rounded-full px-4 py-1.5 text-sm font-bold no-underline"
          >
            {isActive && (
              <motion.span
                layoutId="nav-pill"
                className="absolute inset-0 -z-10 rounded-full border-2 border-ink bg-lime"
                style={{ boxShadow: "var(--shadow-hard-sm)" }}
                transition={{ type: "spring", stiffness: 420, damping: 34 }}
              />
            )}
            <span className={isActive ? "text-ink" : "text-muted"}>
              {item.label}
            </span>
          </NavLink>
        );
      })}
    </nav>
  );
}
