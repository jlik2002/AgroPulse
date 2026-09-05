import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

interface ChipProps {
  children: ReactNode;
  className?: string;
  /** Точка слева — дополнительный, не единственный признак статуса. */
  dot?: string;
  size?: "sm" | "md";
}

export function Chip({ children, className, dot, size = "md" }: ChipProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg font-medium",
        size === "sm" ? "px-2 py-0.5 text-[12px]" : "px-2.5 py-1 text-[13px]",
        className,
      )}
    >
      {dot ? <span className={cn("h-1.5 w-1.5 rounded-full", dot)} /> : null}
      {children}
    </span>
  );
}
