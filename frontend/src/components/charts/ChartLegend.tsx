import { cn } from "@/lib/cn";

export type LegendMark = "solid" | "dashed" | "dashed-dot" | "area" | "bar" | "span";

export interface LegendItem {
  label: string;
  color: string;
  mark: LegendMark;
}

/** Собственная легенда вместо встроенной в ECharts: на макете у рядов
 *  разные начертания — сплошная, пунктир, пунктир с полым кружком, заливка. */
export function ChartLegend({ items, className }: { items: LegendItem[]; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-center gap-x-7 gap-y-2.5", className)}>
      {items.map((item) => (
        <span key={item.label} className="flex items-center gap-2.5 text-[13px] text-ink-soft">
          <Mark mark={item.mark} color={item.color} />
          {item.label}
        </span>
      ))}
    </div>
  );
}

function Mark({ mark, color }: { mark: LegendMark; color: string }) {
  if (mark === "area") {
    return (
      <span
        className="block h-3.5 w-7 rounded-[3px]"
        style={{ backgroundColor: color, opacity: 0.35 }}
      />
    );
  }

  // Отрезок оси, выделенный заливкой с пунктирными границами: так на графике
  // отмечен аномальный период. Без него в легенде красная полоса оставалась
  // самым заметным элементом графика и единственным без объяснения.
  if (mark === "span") {
    return (
      <span
        className="block h-3.5 w-7 rounded-[2px]"
        style={{
          backgroundColor: color,
          opacity: 0.45,
          borderLeft: `1.5px dashed ${color}`,
          borderRight: `1.5px dashed ${color}`,
        }}
      />
    );
  }

  if (mark === "bar") {
    return (
      <span className="flex h-3.5 w-7 items-end gap-[3px]">
        <span className="h-2 w-1.5 rounded-sm" style={{ backgroundColor: color }} />
        <span className="h-3.5 w-1.5 rounded-sm" style={{ backgroundColor: color }} />
        <span className="h-1.5 w-1.5 rounded-sm" style={{ backgroundColor: color }} />
      </span>
    );
  }

  return (
    <svg width="30" height="12" viewBox="0 0 30 12" aria-hidden="true">
      <line
        x1="0"
        y1="6"
        x2="30"
        y2="6"
        stroke={color}
        strokeWidth="2.2"
        strokeDasharray={mark === "solid" ? undefined : "5 4"}
      />
      {mark === "dashed-dot" ? (
        <circle cx="15" cy="6" r="3.4" fill="#FFFFFF" stroke={color} strokeWidth="2" />
      ) : null}
    </svg>
  );
}
