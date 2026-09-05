import { useEffect, useState } from "react";

import type { Field } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Notice } from "@/components/ui/State";
import { CROPS } from "@/lib/crops";
import { Info } from "lucide-react";

export interface FieldDraft {
  name: string;
  crop: string | null;
  sowing_date: string | null;
}

interface FieldEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  field: Field | null;
  onSubmit: (draft: FieldDraft) => void;
  saving?: boolean;
}

/** Карточка редактирования поля: название, культура, дата посева.
 *  Культура и дата посева необязательны — так требует продуктовый сценарий. */
export function FieldEditDialog({
  open,
  onOpenChange,
  field,
  onSubmit,
  saving,
}: FieldEditDialogProps) {
  const [draft, setDraft] = useState<FieldDraft>({ name: "", crop: null, sowing_date: null });

  useEffect(() => {
    if (open && field) {
      setDraft({ name: field.name, crop: field.crop, sowing_date: field.sowing_date });
    }
  }, [open, field]);

  const canSave = draft.name.trim().length > 0;

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Параметры поля"
      description="Культура и дата посева необязательны"
      className="w-[min(520px,calc(100vw-32px))]"
      footer={
        <div className="flex justify-end gap-3">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button
            disabled={!canSave || saving}
            onClick={() => onSubmit({ ...draft, name: draft.name.trim() })}
          >
            {saving ? "Сохраняем…" : "Сохранить"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <label className="block">
          <span className="mb-1.5 block text-[13px] text-ink-soft">Название поля</span>
          <input
            value={draft.name}
            onChange={(event) => setDraft((value) => ({ ...value, name: event.target.value }))}
            className="h-11 w-full rounded-xl border border-line px-3.5 text-[14px] text-ink outline-none transition-colors focus:border-brand-400"
            placeholder="Северное поле"
          />
        </label>

        <label className="block">
          <span className="mb-1.5 block text-[13px] text-ink-soft">Культура</span>
          <input
            list="agro-crops"
            value={draft.crop ?? ""}
            onChange={(event) =>
              setDraft((value) => ({ ...value, crop: event.target.value || null }))
            }
            className="h-11 w-full rounded-xl border border-line px-3.5 text-[14px] text-ink outline-none transition-colors focus:border-brand-400"
            placeholder="Не указана"
          />
          <datalist id="agro-crops">
            {CROPS.map((crop) => (
              <option key={crop} value={crop} />
            ))}
          </datalist>
        </label>

        <label className="block">
          <span className="mb-1.5 block text-[13px] text-ink-soft">Дата посева</span>
          <input
            type="date"
            value={draft.sowing_date ?? ""}
            onChange={(event) =>
              setDraft((value) => ({ ...value, sowing_date: event.target.value || null }))
            }
            className="h-11 w-full rounded-xl border border-line px-3.5 text-[14px] text-ink outline-none transition-colors focus:border-brand-400"
          />
        </label>

        {!draft.crop ? (
          <Notice icon={<Info size={16} />}>
            Без культуры анализ будет основан на собственной истории поля: сезонная норма
            строится по прошлым годам этого же участка.
          </Notice>
        ) : null}
      </div>
    </Modal>
  );
}
