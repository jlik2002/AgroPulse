import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

interface ModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  className,
}: ModalProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[1400] bg-[#0B1A12]/45 animate-fade-in" />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-[1401] w-[min(640px,calc(100vw-32px))] max-h-[calc(100vh-48px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl bg-white p-7 shadow-modal scroll-thin animate-slide-up",
            className,
          )}
        >
          <div className="flex items-start justify-between gap-6">
            <div>
              <Dialog.Title className="text-[22px] font-semibold leading-tight text-ink">
                {title}
              </Dialog.Title>
              {description ? (
                <Dialog.Description className="mt-1.5 text-[14px] text-ink-muted">
                  {description}
                </Dialog.Description>
              ) : null}
            </div>
            <Dialog.Close
              aria-label="Закрыть"
              className="-mr-1 -mt-1 rounded-lg p-1.5 text-ink-muted transition-colors hover:bg-[#F3F4F6] hover:text-ink"
            >
              <X size={20} />
            </Dialog.Close>
          </div>

          <div className="mt-5">{children}</div>

          {footer ? <div className="mt-6">{footer}</div> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
