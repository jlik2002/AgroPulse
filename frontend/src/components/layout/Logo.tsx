import { cn } from "@/lib/cn";

/** Знак AgroPulse: поле с линией пульса в скруглённом квадрате. */
export function Logo({ className, size = 30 }: { className?: string; size?: number }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
        <rect x="1.1" y="1.1" width="29.8" height="29.8" rx="8.4" fill="white" />
        <rect
          x="1.1"
          y="1.1"
          width="29.8"
          height="29.8"
          rx="8.4"
          stroke="#0F422E"
          strokeWidth="2.2"
        />
        {/* Дальний холм и ближнее поле — силуэт угодий. */}
        <path d="M4.4 21.4c3.6-4.6 6.6-6.9 9-6.9 2.4 0 5.4 2.3 9 6.9" stroke="#0F422E" strokeWidth="2.1" strokeLinecap="round" />
        <path d="M4.4 26.6h23.2" stroke="#0F422E" strokeWidth="2.1" strokeLinecap="round" />
        <path d="M18.5 21.4c2.6-3.2 4.7-4.8 6.4-4.8 1 0 1.9.5 2.7 1.4" stroke="#0F422E" strokeWidth="2.1" strokeLinecap="round" />
        {/* Пульс: линия наблюдения поверх поля. */}
        <path
          d="M6.2 11.4h4l2.1-4.3 2.6 7.2 1.9-3.6 1.7 2.2h5.3"
          stroke="#0F422E"
          strokeWidth="2.1"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="text-[21px] font-semibold tracking-tight text-brand-800">AgroPulse</span>
    </span>
  );
}
