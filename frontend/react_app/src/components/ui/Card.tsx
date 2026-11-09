"use client";

// Content card with a fade-up entrance and an optional icon + title row.
// Skeleton / ErrorNote are the shared loading and failure states.

import { m } from "motion/react";
import type { ReactNode } from "react";
import { fadeUp } from "./motion";
import { Icon, type IconName } from "./Icon";

export function Card({
  title,
  icon,
  aside,
  children,
  className = "",
  delay = 0,
}: {
  title?: ReactNode;
  icon?: IconName;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <m.div
      variants={fadeUp}
      initial="hidden"
      animate="show"
      custom={delay}
      className={"card " + className}
    >
      {title ? (
        <div className="mb-3 flex items-start justify-between gap-3">
          <h3 className="flex items-center gap-2 font-semibold">
            {icon ? (
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand-soft text-link">
                <Icon name={icon} size={16} />
              </span>
            ) : null}
            <span>{title}</span>
          </h3>
          {aside}
        </div>
      ) : null}
      {children}
    </m.div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={"skeleton " + className} aria-hidden="true" />;
}

/** Placeholder card used while data loads; announces the label to screen readers. */
export function LoadingCard({ label, rows = 3 }: { label: string; rows?: number }) {
  return (
    <div className="card space-y-3" role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <Skeleton className="h-5 w-1/3" />
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <m.p
      role="alert"
      initial={{ opacity: 0, x: 0 }}
      animate={{ opacity: 1, x: [0, -6, 6, -3, 3, 0] }}
      transition={{ duration: 0.4 }}
      className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger"
    >
      <Icon name="alert" size={16} className="mt-0.5 shrink-0" />
      <span>{children}</span>
    </m.p>
  );
}
