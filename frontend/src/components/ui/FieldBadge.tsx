import { cn } from "@/lib/cn";

interface FieldBadgeProps {
  /** Номер поля в проекте — он же подписан на карте. */
  index: number;
  size?: "sm" | "md" | "lg";
  className?: string;
}

/** Квадратный бейдж с номером поля: одинаковый в списке и на карте,
 *  чтобы пользователь связывал строку панели с контуром. */
export function FieldBadge({ index, size = "md", className }: FieldBadgeProps) {
  const sizes = {
    sm: "h-6 w-6 text-[12px] rounded-[7px]",
    md: "h-8 w-8 text-[14px] rounded-lg",
    lg: "h-10 w-10 text-[16px] rounded-xl",
  } as const;

  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center bg-brand-900 font-semibold text-white",
        sizes[size],
        className,
      )}
    >
      {index}
    </span>
  );
}
