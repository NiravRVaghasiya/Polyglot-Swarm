// Shared motion tokens so every animation in the app has the same rhythm.
// Durations stay within 150–400ms; entrances ease out, presses use springs.

import type { Transition, Variants } from "motion/react";

export const spring: Transition = { type: "spring", stiffness: 420, damping: 32, mass: 0.8 };
export const softSpring: Transition = { type: "spring", stiffness: 260, damping: 28 };
export const easeOut: Transition = { duration: 0.28, ease: [0.22, 1, 0.36, 1] };

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 12 },
  // `custom` on the element is an optional entrance delay in seconds.
  show: (delay: number = 0) => ({ opacity: 1, y: 0, transition: { ...easeOut, delay } }),
};

export const stagger = (step = 0.045, delay = 0): Variants => ({
  hidden: {},
  show: { transition: { staggerChildren: step, delayChildren: delay } },
});

export const pop: Variants = {
  hidden: { opacity: 0, scale: 0.92 },
  show: { opacity: 1, scale: 1, transition: spring },
};
