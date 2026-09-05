import { MousePointer2, Pentagon, PenTool } from "lucide-react";

import { cn } from "@/lib/cn";
import { Tooltip } from "@/components/ui/Tooltip";

export type MapTool = "select" | "parcels" | "draw";

interface MapToolbarProps {
  tool: MapTool;
  onChange: (tool: MapTool) => void;
  parcelsLoading?: boolean;
  className?: string;
}

const TOOLS: { value: MapTool; icon: typeof MousePointer2; hint: string }[] = [
  { value: "select", icon: MousePointer2, hint: "Выбор и перемещение по карте" },
  { value: "parcels", icon: Pentagon, hint: "Показать готовые контуры полей в текущем виде карты" },
  { value: "draw", icon: PenTool, hint: "Нарисовать контур поля вручную" },
];

/** Палитра инструментов слева от карты: выбор, готовые контуры, рисование. */
export function MapToolbar({ tool, onChange, parcelsLoading, className }: MapToolbarProps) {
  return (
    <div
      className={cn(
        "flex flex-col overflow-hidden rounded-xl border border-line bg-white p-1.5 shadow-card",
        className,
      )}
    >
      {TOOLS.map(({ value, icon: Icon, hint }) => {
        const active = tool === value;
        return (
          <Tooltip key={value} content={hint} side="right">
            <button
              type="button"
              aria-label={hint}
              aria-pressed={active}
              onClick={() => onChange(value)}
              className={cn(
                "flex h-11 w-11 items-center justify-center rounded-lg transition-colors",
                active ? "bg-brand-50 text-brand-800" : "text-ink-soft hover:bg-[#F3F4F6]",
                value === "parcels" && parcelsLoading && "animate-pulse",
              )}
            >
              <Icon size={19} strokeWidth={active ? 2.3 : 2} />
            </button>
          </Tooltip>
        );
      })}
    </div>
  );
}
