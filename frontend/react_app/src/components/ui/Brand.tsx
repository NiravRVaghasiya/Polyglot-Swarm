"use client";

import { m } from "motion/react";
import { Icon } from "./Icon";
import { softSpring } from "./motion";

/** App logo mark + wordmark. The globe settles in with a gentle spin on mount. */
export function Brand({ size = "md" }: { size?: "md" | "lg" }) {
  const lg = size === "lg";
  return (
    <span className="inline-flex items-center gap-2.5">
      <m.span
        initial={{ rotate: -90, scale: 0.6, opacity: 0 }}
        animate={{ rotate: 0, scale: 1, opacity: 1 }}
        transition={softSpring}
        className={
          "grid place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-sky-500 text-white shadow-lift " +
          (lg ? "h-12 w-12" : "h-9 w-9")
        }
      >
        <Icon name="globe" size={lg ? 26 : 20} />
      </m.span>
      <span
        className={
          "bg-gradient-to-r from-indigo-600 to-sky-500 bg-clip-text font-extrabold tracking-tight text-transparent dark:from-indigo-300 dark:to-sky-300 " +
          (lg ? "text-3xl" : "text-xl sm:text-2xl")
        }
      >
        Polyglot Swarm
      </span>
    </span>
  );
}
