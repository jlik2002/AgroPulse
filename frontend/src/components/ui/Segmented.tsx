import { cn } from "@/lib/cn";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

interface SegmentedProps<T extends string> {
  value: T;
  options: SegmentedOption<T>[];
  onChange: (value: T) => void;
  className?: string;
  size?: "sm" | "md";
}

/** Переключатель «Карта / Спутник», «RGB / NDVI / NDMI», фильтр типа значения. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  className,
  size = "md",
}: SegmentedProps<T>) {
  return (
    <div
      role="tablist"
      className={cn(
        "inline-flex items-center rounded-xl border border-line bg-white p-1",
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "rounded-lg font-medium transition-colors",
              size === "sm" ? "px-2.5 py-1 text-[12px]" : "px-3.5 py-1.5 text-[13px]",
              active ? "bg-brand-800 text-white" : "text-ink-soft hover:bg-[#F3F4F6]",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
