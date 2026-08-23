/**
 * Folder tabs whose active tab fuses into the panel below it.
 *
 * The seam is the effect: the active tab drops its bottom border and sits 2px
 * lower so it covers the panel's top edge, making tab and panel read as one
 * piece of paper. Without that, thick-bordered tabs look like buttons parked on
 * top of a box.
 *
 * Keyboard behaviour follows the WAI-ARIA tabs pattern — arrow keys move
 * between tabs, Home/End jump to the ends. Browsers give none of this for free
 * on buttons, and a tab strip that only responds to clicks is unusable without
 * a mouse.
 */

import { motion } from "motion/react";
import { useId, useRef } from "react";

export type Tab = { id: string; label: string; badge?: string | number };

export function Tabs({
  tabs,
  active,
  onChange,
  children,
}: {
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
  children: React.ReactNode;
}) {
  const base = useId();
  const strip = useRef<HTMLDivElement>(null);

  function onKeyDown(event: React.KeyboardEvent) {
    const delta =
      event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    let next = -1;
    const index = tabs.findIndex((t) => t.id === active);

    if (delta) next = (index + delta + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;

    event.preventDefault();
    onChange(tabs[next].id);
    // Move focus with selection, or the visible tab and the focused tab drift
    // apart and arrow keys start acting on something the user cannot see.
    strip.current
      ?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
      [next]?.focus();
  }

  return (
    <div>
      <div
        ref={strip}
        role="tablist"
        className="nb-tabstrip"
        onKeyDown={onKeyDown}
      >
        {tabs.map((tab) => {
          const isActive = tab.id === active;
          return (
            <button
              key={tab.id}
              role="tab"
              id={`${base}-tab-${tab.id}`}
              aria-selected={isActive}
              aria-controls={`${base}-panel`}
              // Only the active tab is tabbable; arrows move within the strip.
              // That is the ARIA pattern, and it stops a ten-tab strip from
              // costing ten tab presses to walk past.
              tabIndex={isActive ? 0 : -1}
              onClick={() => onChange(tab.id)}
              className="nb-tab"
            >
              {/* Carries the active tab's outline and fill, and extends 1.5px
                  past its own bottom so it paints over the panel's top border.
                  That erased seam is what makes tab and panel read as one
                  piece of paper rather than a button sitting on a box.

                  It is above the strip background and below the label. At
                  -z-10 it sat behind the tab's own fill and was invisible. */}
              {isActive && (
                <motion.span
                  aria-hidden
                  layoutId="tab-underlay"
                  className="absolute inset-x-0 top-0 rounded-t-[0.9rem] border-1.5 border-b-0 border-edge bg-panel"
                  style={{
                    bottom: "-1.5px",
                    borderWidth: "1.5px",
                    borderBottomWidth: 0,
                  }}
                  transition={{ type: "spring", stiffness: 420, damping: 34 }}
                />
              )}
              <span className="relative">
                {tab.label}
                {tab.badge !== undefined && (
                  <span className="ml-2 rounded-full bg-lime px-2 py-0.5 text-xs font-semibold">
                    {tab.badge}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={`${base}-panel`}
        aria-labelledby={`${base}-tab-${active}`}
        className="nb-tabpanel"
      >
        {children}
      </div>
    </div>
  );
}
