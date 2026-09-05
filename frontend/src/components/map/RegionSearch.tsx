import { Loader2, MapPin, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useRegionSearch } from "@/api/queries";
import type { Region } from "@/api/types";
import { cn } from "@/lib/cn";

interface RegionSearchProps {
  onSelect: (region: Region) => void;
  /** Координаты «широта, долгота» вводятся тем же полем. */
  onCoordinates: (lat: number, lon: number) => void;
  className?: string;
}

const COORDINATES = /^\s*(-?\d{1,3}(?:[.,]\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:[.,]\d+)?)\s*$/;

export function RegionSearch({ onSelect, onCoordinates, className }: RegionSearchProps) {
  const [text, setText] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  // Nominatim просит не частить запросами, поэтому ввод придерживаем.
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(text), 350);
    return () => window.clearTimeout(timer);
  }, [text]);

  useEffect(() => {
    const onClickOutside = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const coordinates = COORDINATES.exec(text);
  const { data, isFetching } = useRegionSearch(coordinates ? "" : debounced);

  // Пустой ответ — тоже результат. Без этого выпадашка просто не открывалась,
  // и пользователь не понимал, ищет сервис или уже ответил «ничего».
  const showEmpty =
    !coordinates && !isFetching && debounced.trim().length >= 2 && data?.length === 0;

  const submitCoordinates = () => {
    if (!coordinates) return;
    const lat = Number(coordinates[1].replace(",", "."));
    const lon = Number(coordinates[2].replace(",", "."));
    if (Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
      onCoordinates(lat, lon);
      setOpen(false);
    }
  };

  return (
    <div ref={boxRef} className={cn("relative", className)}>
      <div className="flex h-12 items-center gap-3 rounded-2xl border border-line bg-white px-4 shadow-card">
        <Search size={18} className="shrink-0 text-ink-muted" />
        <input
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(event) => {
            if (event.key === "Enter") submitCoordinates();
            if (event.key === "Escape") setOpen(false);
          }}
          placeholder="Найти регион или координаты"
          aria-label="Найти регион или координаты"
          className="h-full min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-muted"
        />
        {isFetching ? <Loader2 size={16} className="animate-spin text-ink-muted" /> : null}
      </div>

      {open && (coordinates || (data && data.length > 0) || showEmpty) ? (
        <div className="absolute inset-x-0 top-[54px] overflow-hidden rounded-2xl border border-line bg-white py-1.5 shadow-pop animate-fade-in">
          {coordinates ? (
            <button
              type="button"
              onClick={submitCoordinates}
              className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-brand-50"
            >
              <MapPin size={16} className="shrink-0 text-brand-700" />
              <span className="text-[14px] text-ink">
                Перейти к координатам {coordinates[1]}, {coordinates[2]}
              </span>
            </button>
          ) : showEmpty ? (
            <p className="px-4 py-2.5 text-[14px] text-ink-muted">
              Ничего не нашлось. Попробуйте другое название или введите координаты
              через запятую.
            </p>
          ) : (
            data?.map((region) => (
              <button
                key={`${region.display_name}-${region.lat}-${region.lon}`}
                type="button"
                onClick={() => {
                  onSelect(region);
                  setText(region.display_name);
                  setOpen(false);
                }}
                className="flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-brand-50"
              >
                <MapPin size={16} className="mt-0.5 shrink-0 text-ink-muted" />
                <span className="min-w-0">
                  <span className="block truncate text-[14px] text-ink">{region.display_name}</span>
                  {region.kind ? (
                    <span className="text-[12.5px] text-ink-muted">{region.kind}</span>
                  ) : null}
                </span>
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
