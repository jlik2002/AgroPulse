import { Info } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Notice } from "@/components/ui/State";

export interface FarmDraft {
  name: string;
  legal_form: string | null;
  inn: string | null;
  district: string | null;
  region: string | null;
  contact: string | null;
}

interface FarmEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial: FarmDraft | null;
  mode: "create" | "edit";
  onSubmit: (draft: FarmDraft) => void;
  saving?: boolean;
  error?: string | null;
}

const EMPTY: FarmDraft = {
  name: "",
  legal_form: null,
  inn: null,
  district: null,
  region: null,
  contact: null,
};

/** Карточка хозяйства.
 *
 *  Обязательно только название: по нему хозяйство находят в реестре. Реквизиты
 *  необязательны намеренно — в промышленном внедрении они приезжают из
 *  ведомственного реестра, а требовать ИНН у того, кто просто смотрит на свою
 *  землю, значит закрыть перед ним сервис. Район стоит рядом с ними, потому
 *  что по нему ресурсы распределяются между территориями. */
export function FarmEditDialog({
  open,
  onOpenChange,
  initial,
  mode,
  onSubmit,
  saving,
  error,
}: FarmEditDialogProps) {
  const [draft, setDraft] = useState<FarmDraft>(EMPTY);

  // Заготовка применяется один раз на открытие: родитель собирает объект
  // на каждом рендере, и сравнение по ссылке затирало бы ввод пользователя.
  const filled = useRef(false);
  useEffect(() => {
    if (!open) {
      filled.current = false;
      return;
    }
    if (!filled.current) {
      setDraft(initial ?? EMPTY);
      filled.current = true;
    }
  }, [open, initial]);

  const creating = mode === "create";
  const canSave = draft.name.trim().length > 0;

  const set = (key: keyof FarmDraft) => (value: string) =>
    setDraft((current) => ({ ...current, [key]: value || null }));

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={creating ? "Новое хозяйство" : "Реквизиты хозяйства"}
      description="Поля хозяйства оцениваются вместе — по нему принимается решение о поддержке"
      className="w-[min(560px,calc(100vw-32px))]"
      footer={
        <div className="flex justify-end gap-3">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button
            disabled={!canSave || saving}
            onClick={() => onSubmit({ ...draft, name: draft.name.trim() })}
          >
            {saving ? "Сохраняем…" : creating ? "Создать" : "Сохранить"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <Text
          label={
            <>
              Название <span className="text-danger-ink">*</span>
            </>
          }
          value={draft.name}
          onChange={(value) => setDraft((current) => ({ ...current, name: value }))}
          placeholder="КФХ Иванов"
          autoFocus={creating}
        />

        <div className="grid grid-cols-2 gap-4">
          <Text
            label="Организационно-правовая форма"
            value={draft.legal_form ?? ""}
            onChange={set("legal_form")}
            placeholder="КФХ, ИП, ООО"
          />
          <Text label="ИНН" value={draft.inn ?? ""} onChange={set("inn")} placeholder="2312345678" />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <Text
            label="Муниципальный район"
            value={draft.district ?? ""}
            onChange={set("district")}
            placeholder="Тимашёвский район"
          />
          <Text
            label="Регион"
            value={draft.region ?? ""}
            onChange={set("region")}
            placeholder="Краснодарский край"
          />
        </div>

        <Text
          label="Контакт"
          value={draft.contact ?? ""}
          onChange={set("contact")}
          placeholder="Телефон или адрес электронной почты"
        />

        <Notice icon={<Info size={16} />}>
          Обязательно только название. Остальные сведения нужны отчётам: район —
          для распределения ресурсов между территориями, контакт — чтобы связаться
          с хозяйством до выезда.
        </Notice>

        {error ? <p className="text-[13px] text-danger-ink">{error}</p> : null}
      </div>
    </Modal>
  );
}

interface TextProps {
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}

function Text({ label, value, onChange, placeholder, autoFocus }: TextProps) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] text-ink-soft">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-11 w-full rounded-xl border border-line px-3.5 text-[14px] text-ink outline-none transition-colors focus:border-brand-400"
        placeholder={placeholder}
        autoFocus={autoFocus}
      />
    </label>
  );
}
