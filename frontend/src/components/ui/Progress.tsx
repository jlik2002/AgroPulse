import { cn } from "@/lib/cn";

interface ProgressProps {
  /** 0–100 */
  value: number;
  className?: string;
  tone?: "brand" | "danger";
  height?: "sm" | "md";
}

export function Progress({ value, className, tone = "brand", height = "md" }: ProgressProps) {
  const clamped = Math.min(100, Math.max(0, value));
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn(
        "w-full overflow-hidden rounded-full bg-line-track",
        height === "sm" ? "h-1.5" : "h-2",
        className,
      )}
    >
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-500 ease-out",
          tone === "danger" ? "bg-danger" : "bg-brand-800",
        )}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
