import * as RadixSelect from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface SelectOption {
  value: string;
  label: string;
  hint?: string;
}

interface SelectProps {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  icon?: ReactNode;
  className?: string;
  disabled?: boolean;
  ariaLabel?: string;
}

export function Select({
  value,
  options,
  onChange,
  placeholder = "Выберите",
  icon,
  className,
  disabled,
  ariaLabel,
}: SelectProps) {
  return (
    <RadixSelect.Root value={value} onValueChange={onChange} disabled={disabled}>
      <RadixSelect.Trigger
        aria-label={ariaLabel}
        className={cn(
          "flex h-11 w-full items-center gap-2.5 rounded-xl border border-line bg-white px-3.5 text-[14px] text-ink transition-colors hover:border-[#D6DAE0] disabled:opacity-50 data-[placeholder]:text-ink-muted",
          className,
        )}
      >
        {icon ? <span className="shrink-0 text-ink-muted">{icon}</span> : null}
        <span className="min-w-0 flex-1 truncate text-left">
          <RadixSelect.Value placeholder={placeholder} />
        </span>
        <RadixSelect.Icon className="shrink-0 text-ink-muted">
          <ChevronDown size={16} />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>

      <RadixSelect.Portal>
        <RadixSelect.Content
          position="popper"
          sideOffset={6}
          className="z-popover max-h-72 min-w-[--radix-select-trigger-width] overflow-hidden rounded-xl border border-line bg-white shadow-pop animate-fade-in"
        >
          <RadixSelect.Viewport className="p-1.5">
            {options.map((option) => (
              <RadixSelect.Item
                key={option.value}
                value={option.value}
                className="relative flex cursor-pointer select-none items-center gap-2 rounded-lg py-2 pl-3 pr-8 text-[14px] text-ink outline-none data-[highlighted]:bg-brand-50"
              >
                <RadixSelect.ItemText>{option.label}</RadixSelect.ItemText>
                {option.hint ? (
                  <span className="text-[12px] text-ink-muted">{option.hint}</span>
                ) : null}
                <RadixSelect.ItemIndicator className="absolute right-2.5 text-brand-700">
                  <Check size={15} />
                </RadixSelect.ItemIndicator>
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}
