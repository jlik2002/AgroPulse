import * as RadixTooltip from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

interface InfoTooltipProps {
  children: ReactNode;
  content: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
}

/** Подсказки в макетах объясняют термины (покрытие, NDMI) и причины пропусков. */
export function Tooltip({ children, content, side = "top" }: InfoTooltipProps) {
  return (
    <RadixTooltip.Provider delayDuration={120}>
      <RadixTooltip.Root>
        <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
        <RadixTooltip.Portal>
          <RadixTooltip.Content
            side={side}
            sideOffset={6}
            className="z-tooltip max-w-[280px] rounded-lg border border-line bg-white px-3 py-2 text-[12.5px] leading-snug text-ink-soft shadow-pop animate-fade-in"
          >
            {content}
          </RadixTooltip.Content>
        </RadixTooltip.Portal>
      </RadixTooltip.Root>
    </RadixTooltip.Provider>
  );
}
