import * as RadixSwitch from "@radix-ui/react-switch";

import { cn } from "@/lib/cn";

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  ariaLabel?: string;
}

export function Switch({ checked, onChange, label, ariaLabel }: SwitchProps) {
  return (
    <div className="flex items-center gap-3">
      {label ? <span className="text-[14px] text-ink">{label}</span> : null}
      <RadixSwitch.Root
        checked={checked}
        onCheckedChange={onChange}
        aria-label={ariaLabel ?? label}
        className={cn(
          "relative h-6 w-11 rounded-full transition-colors",
          checked ? "bg-brand-800" : "bg-[#D3D7DD]",
        )}
      >
        <RadixSwitch.Thumb className="block h-5 w-5 translate-x-0.5 rounded-full bg-white shadow-sm transition-transform data-[state=checked]:translate-x-[22px]" />
      </RadixSwitch.Root>
    </div>
  );
}
