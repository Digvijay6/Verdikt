/**
 * Top navigation, where the active item is a folder tab on the page itself.
 *
 * The page is one sheet and this strip sits on its top edge. The active item
 * breaks through that edge and fuses with the sheet - its bottom border is
 * gone and it paints over the segment of the sheet's border running beneath
 * it, so no line separates tab from page. Inactive items get no chrome at all,
 * which is what preserves the front-to-back reading: one thing attached to the
 * page, the rest on the layer behind.
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
    <nav className="flex items-end" aria-label="Main">
      {items.map((item) => {
        const isActive = item === active;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            aria-current={isActive ? "page" : undefined}
            className="app-navitem"
          >
            {/* Carries the tab's fill and outline, and extends one hairline
                past its own bottom to paint over the sheet's top border. That
                erased seam is the whole effect. */}
            {isActive && (
              <motion.span
                aria-hidden
                layoutId="nav-tab"
                className="absolute inset-x-0 top-0 bg-lime"
                style={{
                  bottom: "calc(-1 * var(--edge-w))",
                  border: "var(--edge-w) solid var(--color-edge)",
                  borderBottom: "none",
                  borderRadius: "var(--radius-btn) var(--radius-btn) 0 0",
                }}
                transition={{ type: "spring", stiffness: 420, damping: 34 }}
              />
            )}
            <span className="relative">{item.label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}
