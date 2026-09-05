import * as RadixCheckbox from "@radix-ui/react-checkbox";
import { Check } from "lucide-react";
import { useId } from "react";

import { cn } from "@/lib/cn";

interface CheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Видимая подпись. Не задана — подпись переходит в `aria-label`,
   *  и флажок остаётся доступным с клавиатуры и для чтения с экрана. */
  label?: string;
  ariaLabel?: string;
  className?: string;
  disabled?: boolean;
}

export function Checkbox({
  checked,
  onChange,
  label,
  ariaLabel,
  className,
  disabled,
}: CheckboxProps) {
  const id = useId();
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <RadixCheckbox.Root
        id={id}
        checked={checked}
        disabled={disabled}
        aria-label={label ? undefined : (ariaLabel ?? "Отметить")}
        onCheckedChange={(state) => onChange(state === true)}
        className={cn(
          "flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] border transition-colors",
          checked ? "border-brand-800 bg-brand-800 text-white" : "border-[#C9CDD4] bg-white",
          disabled && "opacity-45",
        )}
      >
        <RadixCheckbox.Indicator>
          <Check size={13} strokeWidth={3} />
        </RadixCheckbox.Indicator>
      </RadixCheckbox.Root>
      {label ? (
        <label htmlFor={id} className="cursor-pointer select-none text-[14px] text-ink">
          {label}
        </label>
      ) : null}
    </div>
  );
}
