import { Info } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { Farm } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Select } from "@/components/ui/Select";
import { Notice } from "@/components/ui/State";
import { CROPS } from "@/lib/crops";

/** Значение селектора, означающее «завести хозяйство прямо здесь».
 *  Отдельный экран ради одного поля ввода заставил бы бросить рисование
 *  контура на полпути. */
const NEW_FARM = "__new__";

export interface FieldDraft {
  name: string;
  /** Хозяйство-владелец. Обязательно, если не заводится новое. */
  farm_id: string | null;
  /** Название нового хозяйства. Родитель создаёт его перед полем. */
  new_farm_name: string | null;
  crop: string | null;
  sowing_date: string | null;
}

interface FieldEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Заготовка полей формы. При создании — из контура, при правке — из поля. */
  initial: FieldDraft | null;
  mode: "create" | "edit";
  farms: Farm[];
  onSubmit: (draft: FieldDraft) => void;
  saving?: boolean;
  error?: string | null;
}

/** Карточка поля: название, культура, дата посева.
 *
 *  Один и тот же диалог обслуживает создание и правку. Это не экономия кода:
 *  требования к набору данных у обоих случаев одинаковые, и раздвоение формы
 *  быстро привело бы к тому, что при создании культуру спросить забыли.
 *
 *  Культура обязательна и относится к текущему сезону. Дата посева — нет:
 *  на расчёт она не влияет, а знают её далеко не всегда. */
export function FieldEditDialog({
  open,
  onOpenChange,
  initial,
  mode,
  farms,
  onSubmit,
  saving,
  error,
}: FieldEditDialogProps) {
  const [draft, setDraft] = useState<FieldDraft>({
    name: "",
    farm_id: null,
    new_farm_name: null,
    crop: null,
    sowing_date: null,
  });

  // Заготовка применяется один раз на открытие. Сравнивать её по ссылке нельзя:
  // родитель собирает объект на каждом рендере, и форма затирала бы ввод
  // пользователя при любом обновлении списка полей.
  const filled = useRef(false);
  useEffect(() => {
    if (!open) {
      filled.current = false;
      return;
    }
    if (!filled.current && initial) {
      // Единственное хозяйство подставляется само: в проекте, где оно одно,
      // выбор из списка длиной в один пункт — лишний клик на каждом поле.
      const only = farms.length === 1 ? farms[0].id : null;
      setDraft({ ...initial, farm_id: initial.farm_id ?? only });
      filled.current = true;
    }
  }, [open, initial, farms]);

  const creating = mode === "create";
  const addingFarm = draft.farm_id === NEW_FARM;
  const farmChosen = addingFarm
    ? (draft.new_farm_name ?? "").trim().length > 0
    : Boolean(draft.farm_id);
  const canSave =
    draft.name.trim().length > 0 && (draft.crop ?? "").trim().length > 0 && farmChosen;

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={creating ? "Новое поле" : "Параметры поля"}
      description="Культура — та, что растёт на поле в этом сезоне"
      className="w-[min(520px,calc(100vw-32px))]"
      footer={
        <div className="flex justify-end gap-3">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button
            disabled={!canSave || saving}
            onClick={() =>
              onSubmit({
                ...draft,
                name: draft.name.trim(),
                crop: (draft.crop ?? "").trim() || null,
                farm_id: addingFarm ? null : draft.farm_id,
                new_farm_name: addingFarm ? (draft.new_farm_name ?? "").trim() : null,
              })
            }
          >
            {saving ? "Сохраняем…" : creating ? "Добавить поле" : "Сохранить"}
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

        <div>
          <span className="mb-1.5 block text-[13px] text-ink-soft">
            Хозяйство <span className="text-danger-ink">*</span>
          </span>
          <Select
            value={draft.farm_id ?? ""}
            options={[
              ...farms.map((farm) => ({
                value: farm.id,
                label: farm.name,
                hint: farm.district ?? undefined,
              })),
              { value: NEW_FARM, label: "Новое хозяйство…" },
            ]}
            onChange={(value) =>
              setDraft((current) => ({
                ...current,
                farm_id: value,
                new_farm_name: value === NEW_FARM ? (current.new_farm_name ?? "") : null,
              }))
            }
            placeholder="Выберите хозяйство"
            ariaLabel="Хозяйство"
          />
          {addingFarm ? (
            <input
              value={draft.new_farm_name ?? ""}
              onChange={(event) =>
                setDraft((current) => ({ ...current, new_farm_name: event.target.value }))
              }
              className="mt-2 h-11 w-full rounded-xl border border-line px-3.5 text-[14px] text-ink outline-none transition-colors focus:border-brand-400"
              placeholder="Название хозяйства"
              autoFocus
            />
          ) : null}
        </div>

        <label className="block">
          <span className="mb-1.5 block text-[13px] text-ink-soft">
            Культура <span className="text-danger-ink">*</span>
          </span>
          <input
            list="agro-crops"
            value={draft.crop ?? ""}
            onChange={(event) =>
              setDraft((value) => ({ ...value, crop: event.target.value || null }))
            }
            className="h-11 w-full rounded-xl border border-line px-3.5 text-[14px] text-ink outline-none transition-colors focus:border-brand-400"
            placeholder="Выберите из списка или введите свою"
            autoFocus={creating}
          />
          <datalist id="agro-crops">
            {CROPS.map((crop) => (
              <option key={crop} value={crop} />
            ))}
          </datalist>
        </label>

        <label className="block">
          <span className="mb-1.5 block text-[13px] text-ink-soft">
            Дата посева <span className="text-ink-muted">— если известна</span>
          </span>
          <input
            type="date"
            value={draft.sowing_date ?? ""}
            onChange={(event) =>
              setDraft((value) => ({ ...value, sowing_date: event.target.value || null }))
            }
            className="h-11 w-full rounded-xl border border-line px-3.5 text-[14px] text-ink outline-none transition-colors focus:border-brand-400"
          />
        </label>

        {/* Объясняем не «что ввести», а зачем: норма поля собирается по его
            прошлым сезонам, в которых культура могла быть другой. */}
        <Notice icon={<Info size={16} />}>
          Сезонная норма строится по прошлым годам этого же участка. Зная культуру текущего
          сезона, мы отличаем севооборот от угнетения посевов. Хозяйство определяет, в чью
          строку реестра поддержки сложится результат.
        </Notice>

        {error ? <p className="text-[13px] text-danger-ink">{error}</p> : null}
      </div>
    </Modal>
  );
}
