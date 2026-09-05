import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

const button = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl font-medium transition-colors disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        // Основное действие экрана: «Запустить анализ», «Скачать PDF».
        primary: "bg-brand-800 text-white hover:bg-brand-700 active:bg-brand-900",
        // Второстепенное действие рядом с основным: «Назад», «CSV».
        outline: "border border-line bg-white text-ink hover:bg-[#F7F8F9] active:bg-[#F1F2F4]",
        ghost: "text-ink hover:bg-[#F3F4F6]",
        link: "text-brand-700 underline-offset-4 hover:underline",
        danger: "bg-danger text-white hover:bg-[#CC1F26]",
      },
      size: {
        sm: "h-8 px-3 text-[13px]",
        md: "h-10 px-4 text-[14px]",
        lg: "h-12 px-6 text-[15px]",
        icon: "h-10 w-10",
      },
      block: { true: "w-full", false: "" },
    },
    defaultVariants: { variant: "primary", size: "md", block: false },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, block, asChild = false, ...props }, ref) => {
    const Component = asChild ? Slot : "button";
    return (
      <Component
        ref={ref}
        className={cn(button({ variant, size, block }), className)}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
