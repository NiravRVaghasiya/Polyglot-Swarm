"use client";

// Dashboard section navigation. One tablist that is a floating bottom bar on
// phones and a pill bar under the header on larger screens, with a sliding
// active indicator.
//
// Panels stay MOUNTED when inactive (only hidden), so switching tabs never
// drops a live chat session, a half-answered listening task or loaded data —
// the features behave exactly as they did on the single long page.

import { m, useAnimationControls } from "motion/react";
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { Icon, type IconName } from "./Icon";
import { easeOut, spring } from "./motion";

export interface TabDef<T extends string> {
  id: T;
  label: string;
  icon: IconName;
}

export function TabNav<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: readonly TabDef<T>[];
  active: T;
  onChange: (id: T) => void;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(e: KeyboardEvent, index: number) {
    let next = -1;
    if (e.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    if (next < 0) return;
    e.preventDefault();
    onChange(tabs[next].id);
    refs.current[next]?.focus();
  }

  return (
    <nav
      aria-label="Sections"
      className={
        // Mobile: floating bottom bar clear of the home indicator.
        "fixed inset-x-3 bottom-[max(0.75rem,env(safe-area-inset-bottom))] z-40 " +
        // Desktop: inline pill bar.
        "sm:static sm:inset-auto sm:z-auto"
      }
    >
      <div
        role="tablist"
        aria-orientation="horizontal"
        className="mx-auto grid max-w-md grid-cols-4 gap-1 rounded-2xl border border-line/80 bg-surface/85 p-1.5 shadow-lift backdrop-blur-md sm:max-w-none sm:shadow-card"
      >
        {tabs.map((t, i) => {
          const selected = t.id === active;
          return (
            <button
              key={t.id}
              ref={(el) => {
                refs.current[i] = el;
              }}
              id={`tab-${t.id}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`panel-${t.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(t.id)}
              onKeyDown={(e) => onKeyDown(e, i)}
              className={
                "relative flex min-h-12 flex-col items-center justify-center gap-0.5 rounded-xl px-2 text-[11px] font-semibold " +
                "transition-colors duration-200 sm:flex-row sm:gap-2 sm:text-sm " +
                (selected ? "text-brand-fg" : "text-muted hover:text-fg")
              }
            >
              {selected ? (
                <m.span
                  layoutId="dashboard-tab-pill"
                  transition={spring}
                  className="absolute inset-0 rounded-xl bg-brand shadow-lift"
                />
              ) : null}
              <m.span
                className="relative"
                animate={selected ? { scale: 1.08, y: -1 } : { scale: 1, y: 0 }}
                transition={spring}
              >
                <Icon name={t.icon} size={18} />
              </m.span>
              <span className="relative">{t.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}

export function TabPanel({
  id,
  active,
  direction,
  children,
}: {
  id: string;
  active: boolean;
  /** -1 when arriving from a tab to the right, 1 from the left. */
  direction: number;
  children: ReactNode;
}) {
  const controls = useAnimationControls();
  const mounted = useRef(false);

  // Slide + fade in whenever this panel becomes the active one (not on the
  // initial page load, where the content is already in place).
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    if (!active) return;
    void controls.start({
      opacity: [0, 1],
      x: [direction * 24, 0],
      transition: easeOut,
    });
  }, [active, direction, controls]);

  return (
    <m.section
      id={`panel-${id}`}
      role="tabpanel"
      aria-labelledby={`tab-${id}`}
      hidden={!active}
      animate={controls}
    >
      {children}
    </m.section>
  );
}
