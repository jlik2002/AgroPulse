import * as Popover from "@radix-ui/react-popover";
import { MoreVertical, Pencil, Trash2 } from "lucide-react";

import type { Field } from "@/api/types";
import { FieldBadge } from "@/components/ui/FieldBadge";
import { cn } from "@/lib/cn";
import { formatArea, formatDate } from "@/lib/format";

interface FieldListItemProps {
  field: Field;
  index: number;
  active?: boolean;
  onSelect?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
}

/** Строка списка полей проекта. Номер повторяет подпись контура на карте —
 *  так пользователь связывает строку панели с конкретным участком. */
export function FieldListItem({
  field,
  index,
  active,
  onSelect,
  onEdit,
  onDelete,
}: FieldListItemProps) {
  return (
    <div
      onMouseEnter={onSelect}
      className={cn(
        "group relative rounded-2xl border px-4 py-3.5 transition-colors",
        active ? "border-brand-300 bg-brand-50" : "border-line bg-white hover:border-[#D6DAE0]",
      )}
    >
      <div className="flex items-start gap-3.5">
        <FieldBadge index={index} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[17px] font-semibold leading-snug text-ink">{field.name}</p>
          <p className="mt-0.5 text-[15px] text-ink-soft">{formatArea(field.area_ha)}</p>
          <p className="mt-0.5 text-[13.5px] text-ink-muted">
            {field.crop
              ? `${field.crop}${field.sowing_date ? ` · ${formatDate(field.sowing_date)}` : ""}`
              : "Культура не указана"}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-0.5">
          {onEdit ? (
            <button
              type="button"
              aria-label={`Изменить параметры поля «${field.name}»`}
              onClick={onEdit}
              className="rounded-lg p-1.5 text-ink-soft transition-colors hover:bg-white hover:text-brand-700"
            >
              <Pencil size={17} />
            </button>
          ) : null}

          {onDelete ? (
            <Popover.Root>
              <Popover.Trigger
                aria-label={`Действия с полем «${field.name}»`}
                className="rounded-lg p-1.5 text-ink-soft transition-colors hover:bg-white hover:text-ink"
              >
                <MoreVertical size={17} />
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  align="end"
                  sideOffset={4}
                  className="z-popover w-52 overflow-hidden rounded-xl border border-line bg-white p-1.5 shadow-pop animate-fade-in"
                >
                  <Popover.Close asChild>
                    <button
                      type="button"
                      onClick={onDelete}
                      className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[14px] text-danger-ink transition-colors hover:bg-danger-tint"
                    >
                      <Trash2 size={16} />
                      Удалить поле
                    </button>
                  </Popover.Close>
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
          ) : null}
        </div>
      </div>
    </div>
  );
}
