"use client";

// Loads Framer Motion's feature bundle once (LazyMotion keeps the per-
// component cost tiny: components use the lightweight `m.*` elements) and
// honours the OS "reduce motion" setting app-wide: transform/layout motion is
// switched off, opacity fades remain.

import { LazyMotion, MotionConfig, domMax } from "motion/react";
import type { ReactNode } from "react";

export function MotionProvider({ children }: { children: ReactNode }) {
  return (
    <LazyMotion features={domMax} strict>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </LazyMotion>
  );
}
