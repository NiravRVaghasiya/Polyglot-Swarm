"use client";

// Animated button: springy press/hover feedback via Framer Motion, a spinner
// for async work, and consistent variants. It is still a native <button>, so
// text, labels, `disabled` and form submission behave exactly as before.

import { m, type HTMLMotionProps } from "motion/react";
import type { ReactNode } from "react";
import { spring } from "./motion";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
type Size = "sm" | "md" | "lg" | "icon";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand text-brand-fg shadow-sm shadow-brand/30 hover:shadow-lift hover:brightness-110",
  secondary: "border border-line bg-surface text-fg shadow-sm hover:border-brand/40 hover:bg-surface2",
  ghost: "text-muted hover:bg-surface2 hover:text-fg",
  danger: "bg-red-600 text-white shadow-sm shadow-red-600/30 hover:brightness-110",
  success: "bg-emerald-600 text-white shadow-sm shadow-emerald-600/30 hover:brightness-110",
};

const SIZES: Record<Size, string> = {
  sm: "min-h-9 px-3 text-sm gap-1.5",
  md: "min-h-11 px-4 text-sm gap-2",
  lg: "min-h-12 px-5 text-base gap-2",
  icon: "h-11 w-11 justify-center",
};

export type ButtonProps = Omit<HTMLMotionProps<"button">, "children"> & {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  children?: ReactNode;
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  className = "",
  disabled,
  children,
  ...props
}: ButtonProps) {
  const inactive = disabled || loading;
  return (
    <m.button
      whileHover={inactive ? undefined : { y: -1 }}
      whileTap={inactive ? undefined : { scale: 0.96 }}
      transition={spring}
      disabled={disabled}
      aria-busy={loading || undefined}
      className={
        "relative inline-flex select-none items-center justify-center rounded-xl font-semibold " +
        "transition-[background-color,border-color,box-shadow,filter,color,opacity] duration-200 " +
        "disabled:opacity-50 disabled:shadow-none " +
        VARIANTS[variant] +
        " " +
        SIZES[size] +
        " " +
        className
      }
      {...props}
    >
      {loading ? <Spinner /> : null}
      {children}
    </m.button>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={"animate-spin " + className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
