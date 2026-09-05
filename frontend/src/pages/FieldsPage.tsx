import type { Map as LeafletMap } from "leaflet";
import { Info, PenTool, RefreshCw } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  useCreateField,
  useDeleteField,
  useSearchParcels,
  useStartProjectProcessing,
  useUpdateField,
  useUpdateProject,
} from "@/api/queries";
import type { Parcel, PolygonGeometry, Region } from "@/api/types";
import { useProjectContext } from "@/app/ProjectContext";
import { FieldEditDialog, type FieldDraft } from "@/components/field/FieldEditDialog";
import { FieldListItem } from "@/components/field/FieldListItem";
import { PreflightDialog } from "@/components/field/PreflightDialog";
import { BASEMAP_OPTIONS, type BasemapKind } from "@/components/map/basemaps";
import { DrawLayer } from "@/components/map/DrawLayer";
import { FieldShape } from "@/components/map/FieldShapes";
import { FitBounds, FlyTo, MapCanvas } from "@/components/map/MapCanvas";
import { MapToolbar, type MapTool } from "@/components/map/MapToolbar";
import { ScaleBar, ZoomControls } from "@/components/map/MapControls";
import { RegionSearch } from "@/components/map/RegionSearch";
import { Button } from "@/components/ui/Button";
import { DateRange } from "@/components/ui/DateRange";
import { Segmented } from "@/components/ui/Segmented";
import { EmptyState, Notice } from "@/components/ui/State";
import { combinedBounds } from "@/lib/geo";
import { fieldsWord } from "@/lib/format";

/** Первый экран проекта: карта, выбор готовых контуров, ручное рисование
 *  и список добавленных полей с периодом анализа. */
export function FieldsPage() {
  const navigate = useNavigate();
  const { project, fields, refetchFields } = useProjectContext();

  const [basemap, setBasemap] = useState<BasemapKind>("satellite");
  const [tool, setTool] = useState<MapTool>("select");
  const [parcels, setParcels] = useState<Parcel[]>([]);
  const [activeFieldId, setActiveFieldId] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [preflight, setPreflight] = useState(false);
  const [flyTo, setFlyTo] = useState<[number, number] | null>(null);
  const [addedRefs, setAddedRefs] = useState<Set<string>>(new Set());
  const [map, setMap] = useState<LeafletMap | null>(null);

  const createField = useCreateField(project.id);
  const updateField = useUpdateField(project.id);
  const deleteField = useDeleteField(project.id);
  const updateProject = useUpdateProject(project.id);
  const searchParcels = useSearchParcels();
  const startProcessing = useStartProjectProcessing(project.id);

  const fieldBounds = useMemo(
    () => combinedBounds(fields.map((field) => field.geometry)),
    [fields],
  );

  // Уже добавленные контуры не предлагаем повторно: ссылка на объект OSM
  // в ответе поля не возвращается, поэтому помним их на клиенте.
  const availableParcels = useMemo(
    () => parcels.filter((parcel) => !addedRefs.has(parcel.external_ref)),
    [parcels, addedRefs],
  );

  const loadParcels = useCallback(() => {
    if (!map) return;
    const bounds = map.getBounds();
    searchParcels.mutate(
      {
        west: bounds.getWest(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        north: bounds.getNorth(),
      },
      { onSuccess: setParcels },
    );
  }, [map, searchParcels]);

  const onToolChange = (next: MapTool) => {
    setTool(next);
    if (next === "parcels") loadParcels();
  };

  const addGeometry = (geometry: PolygonGeometry, options?: Partial<Parcel>) => {
    const index = fields.length + 1;
    createField.mutate(
      {
        name: options?.name ?? `Поле ${index}`,
        geometry,
        crop: options?.crop ?? null,
        source: options?.external_ref ? "osm" : "drawn",
        external_ref: options?.external_ref ?? null,
      },
      {
        onSuccess: (field) => {
          setActiveFieldId(field.id);
          setTool("select");
          if (options?.external_ref) {
            setAddedRefs((previous) => new Set(previous).add(options.external_ref as string));
          }
        },
      },
    );
  };

  const onRegionSelect = (region: Region) => {
    setFlyTo([region.lat, region.lon]);
    setParcels([]);
  };

  const editingField = fields.find((field) => field.id === editing) ?? null;

  return (
    <div className="flex min-h-0 flex-1">
      {/* --- карта --- */}
      <div className="relative min-w-0 flex-1">
        <MapCanvas basemap={basemap} onReady={setMap}>
          <ScaleBar />
          <div className="absolute bottom-[92px] left-6 z-[500]">
            <ZoomControls
              onLocate={
                fieldBounds
                  ? () => map?.fitBounds(fieldBounds, { padding: [40, 40], maxZoom: 15 })
                  : undefined
              }
            />
          </div>
          <FitBounds bounds={fieldBounds} once />
          <FlyTo center={flyTo} zoom={13} />
          <DrawLayer active={tool === "draw"} onCreate={(geometry) => addGeometry(geometry)} />

          {/* Готовые контуры из открытых источников — белым, до добавления. */}
          {tool === "parcels"
            ? availableParcels.map((parcel, index) => (
                <FieldShape
                  key={parcel.external_ref}
                  geometry={parcel.geometry}
                  style={{ color: "#FFFFFF", fillOpacity: 0.18, weight: 2 }}
                  label={`${parcelName(parcel, index)} · ${Math.round(parcel.area_ha)} га`}
                  onClick={() =>
                    addGeometry(parcel.geometry, {
                      name: parcelName(parcel, fields.length),
                      crop: parcel.crop,
                      external_ref: parcel.external_ref,
                    })
                  }
                />
              ))
            : null}

          {fields.map((field, index) => (
            <FieldShape
              key={field.id}
              geometry={field.geometry}
              index={index + 1}
              style={{
                color: "#8FC45B",
                badgeColor: "#0D3A28",
                fillOpacity: activeFieldId === field.id ? 0.62 : 0.45,
                weight: 2.5,
              }}
              label={field.name}
              onClick={() => setActiveFieldId(field.id)}
            />
          ))}
        </MapCanvas>

        <RegionSearch
          className="absolute left-6 top-6 z-[500] w-[400px]"
          onSelect={onRegionSelect}
          onCoordinates={(lat, lon) => setFlyTo([lat, lon])}
        />

        <Segmented
          className="absolute right-6 top-6 z-[500] shadow-card"
          value={basemap}
          options={BASEMAP_OPTIONS}
          onChange={(value) => setBasemap(value as BasemapKind)}
        />

        <MapToolbar
          className="absolute left-6 top-[104px] z-[500]"
          tool={tool}
          onChange={onToolChange}
          parcelsLoading={searchParcels.isPending}
        />

        {tool === "parcels" ? (
          <div className="absolute bottom-6 left-1/2 z-[500] -translate-x-1/2">
            <div className="flex items-center gap-3 rounded-xl border border-line bg-white px-4 py-2.5 shadow-pop">
              <span className="text-[13.5px] text-ink-soft">
                {searchParcels.isPending
                  ? "Ищем контуры пашни в текущем виде карты…"
                  : availableParcels.length > 0
                    ? `Найдено ${availableParcels.length} ${fieldsWord(availableParcels.length)} — нажмите на контур, чтобы добавить`
                    : "В этом районе готовых контуров нет — нарисуйте поле вручную"}
              </span>
              <Button
                size="sm"
                variant="outline"
                onClick={loadParcels}
                disabled={searchParcels.isPending}
              >
                <RefreshCw size={15} />
                Обновить
              </Button>
            </div>
          </div>
        ) : null}

        {tool === "draw" ? (
          <div className="pointer-events-none absolute bottom-6 left-1/2 z-[500] -translate-x-1/2 rounded-xl bg-brand-900/92 px-4 py-2.5 text-[13.5px] text-white shadow-pop">
            Отмечайте вершины по контуру поля, замкните контур в первой точке
          </div>
        ) : null}
      </div>

      {/* --- панель проекта --- */}
      <aside className="flex w-[420px] shrink-0 flex-col border-l border-line bg-white xl:w-[480px]">
        <div className="px-7 pb-4 pt-6">
          <h1 className="flex items-center gap-3 text-[24px] font-semibold leading-tight text-ink">
            Поля проекта
            <span className="rounded-md bg-brand-50 px-2 py-0.5 text-[15px] font-semibold text-brand-800 tnum">
              {fields.length}
            </span>
          </h1>
          <p className="mt-1.5 text-[14px] text-ink-muted">
            Выберите готовый контур или нарисуйте поле вручную
          </p>
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-7 scroll-thin">
          {fields.length === 0 ? (
            <EmptyState
              title="Поля пока не добавлены"
              description="Найдите регион в строке поиска, покажите готовые контуры пашни или обведите участок вручную."
            />
          ) : (
            fields.map((field, index) => (
              <FieldListItem
                key={field.id}
                field={field}
                index={index + 1}
                active={activeFieldId === field.id}
                onSelect={() => setActiveFieldId(field.id)}
                onEdit={() => setEditing(field.id)}
                onDelete={() => deleteField.mutate(field.id)}
              />
            ))
          )}

          <Button
            variant="outline"
            block
            className="h-14 border-brand-200 text-[15px] font-medium text-brand-800 hover:bg-brand-50"
            onClick={() => onToolChange("draw")}
          >
            <PenTool size={18} />
            Нарисовать поле
          </Button>
        </div>

        <div className="space-y-4 border-t border-line px-7 py-5">
          <div>
            <h2 className="mb-2.5 text-[17px] font-semibold text-ink">Период анализа</h2>
            <DateRange
              from={project.period_from}
              to={project.period_to}
              onChange={(range) =>
                updateProject.mutate({ period_from: range.from, period_to: range.to })
              }
            />
          </div>

          <Notice icon={<Info size={17} />} className="border-none bg-transparent px-0 py-0">
            Без культуры анализ будет основан
            <br />
            на собственной истории поля
          </Notice>

          <Button
            size="lg"
            block
            disabled={fields.length === 0}
            onClick={() => setPreflight(true)}
          >
            Запустить анализ · {fields.length} {fieldsWord(fields.length)}
          </Button>
          <p className="text-center text-[13px] text-ink-muted">Обычно занимает 2–4 минуты</p>
        </div>
      </aside>

      <FieldEditDialog
        open={Boolean(editing)}
        onOpenChange={(open) => !open && setEditing(null)}
        field={editingField}
        saving={updateField.isPending}
        onSubmit={(draft: FieldDraft) => {
          if (!editingField) return;
          updateField.mutate(
            { fieldId: editingField.id, payload: draft },
            { onSuccess: () => setEditing(null) },
          );
        }}
      />

      <PreflightDialog
        open={preflight}
        onOpenChange={setPreflight}
        project={project}
        fields={fields}
        starting={startProcessing.isPending}
        onConfirm={() =>
          startProcessing.mutate(undefined, {
            onSuccess: () => {
              setPreflight(false);
              refetchFields();
              navigate(`/p/${project.id}/processing`);
            },
          })
        }
      />
    </div>
  );
}

/** Имя для контура из открытого источника: у OSM оно есть далеко не всегда. */
function parcelName(parcel: Parcel, index: number): string {
  return parcel.name?.trim() || `Поле ${index + 1}`;
}
