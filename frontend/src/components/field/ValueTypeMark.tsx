import { VALUE_TYPE } from "@/lib/status";
import type { ValueType } from "@/api/types";

/** Начертание ряда рядом с текстовой меткой типа значения.
 *  Строки таблицы целиком не закрашиваются — так требует макет. */
export function ValueTypeMark({ type }: { type: ValueType }) {
  const color = VALUE_TYPE[type].stroke;

  if (type === "observed") {
    return (
      <svg width="30" height="12" viewBox="0 0 30 12" aria-hidden="true">
        <line x1="4" y1="6" x2="26" y2="6" stroke={color} strokeWidth="2.2" />
        <circle cx="4" cy="6" r="3.4" fill={color} />
        <circle cx="26" cy="6" r="3.4" fill={color} />
      </svg>
    );
  }

  if (type === "restored") {
    return (
      <svg width="30" height="12" viewBox="0 0 30 12" aria-hidden="true">
        <line x1="4" y1="6" x2="26" y2="6" stroke={color} strokeWidth="2.2" strokeDasharray="4 3" />
        <circle cx="4" cy="6" r="3.2" fill="#FFFFFF" stroke={color} strokeWidth="2" />
        <circle cx="26" cy="6" r="3.2" fill="#FFFFFF" stroke={color} strokeWidth="2" />
      </svg>
    );
  }

  return (
    <svg width="30" height="12" viewBox="0 0 30 12" aria-hidden="true">
      <line x1="4" y1="6" x2="26" y2="6" stroke={color} strokeWidth="2.2" strokeDasharray="3 3" />
      <circle cx="4" cy="6" r="3.4" fill={color} />
      <circle cx="26" cy="6" r="3.4" fill={color} />
    </svg>
  );
}
