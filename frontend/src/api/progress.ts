/** Подписка на поток прогресса обработки (SSE).
 *
 *  Первым сообщением бэкенд присылает полный снимок стадий, поэтому клиент,
 *  открывший страницу в середине расчёта или перезагрузивший её, сразу видит
 *  реальное состояние, а не пустой список. Переподключение при обрыве делает
 *  сам `EventSource` — своей логики ретраев здесь не нужно. */

import { useEffect, useMemo, useRef, useState } from "react";

import { apiUrl } from "@/api/client";
import type { ProgressSnapshot, StageEvent, StageState } from "@/api/types";

export interface FieldProgress {
  /** Стадии по порядку, как их показывает макет «Обработка данных». */
  stages: StageState[];
  /** Доля выполнения поля: усреднение по всем девяти стадиям. */
  percent: number;
  done: boolean;
  failed: boolean;
  /** Текущая стадия — та, что выполняется; если всё готово, последняя. */
  current: StageState | null;
}

export interface ProgressState {
  connected: boolean;
  stages: { stage: string; title: string; index: number }[];
  stageTotal: number;
  byField: Record<string, FieldProgress>;
  /** Поля, о завершении которых пришло отдельное событие. */
  finished: Set<string>;
  /** Хронология событий для ленты «Последние события». */
  log: { at: string; fieldId: string; text: string; status: string }[];
}

const EMPTY: ProgressState = {
  connected: false,
  stages: [],
  stageTotal: 9,
  byField: {},
  finished: new Set(),
  log: [],
};

const MAX_LOG = 40;

export function useProjectProgress(projectId: string | undefined, enabled = true): ProgressState {
  const [snapshot, setSnapshot] = useState<ProgressSnapshot | null>(null);
  const [events, setEvents] = useState<StageEvent[]>([]);
  const [finished, setFinished] = useState<Set<string>>(new Set());
  const [connected, setConnected] = useState(false);
  const logRef = useRef<ProgressState["log"]>([]);
  const [logVersion, setLogVersion] = useState(0);

  useEffect(() => {
    if (!projectId || !enabled) return;

    const source = new EventSource(apiUrl(`/projects/${projectId}/events`));

    source.addEventListener("open", () => setConnected(true));

    source.addEventListener("snapshot", (event) => {
      setConnected(true);
      setSnapshot(JSON.parse((event as MessageEvent).data) as ProgressSnapshot);
    });

    source.addEventListener("progress", (event) => {
      const payload = JSON.parse((event as MessageEvent).data);
      if (payload.type === "stage") {
        const stage = payload as StageEvent;
        setEvents((previous) => [...previous, stage]);
        pushLog(logRef, {
          at: stage.at,
          fieldId: stage.field_id,
          status: stage.status,
          text:
            stage.status === "failed"
              ? `${stage.stage_title}: ошибка`
              : stage.message
                ? `${stage.stage_title} — ${stage.message}`
                : stage.stage_title,
        });
        setLogVersion((value) => value + 1);
      } else if (payload.type === "field_done") {
        setFinished((previous) => new Set(previous).add(payload.field_id));
        pushLog(logRef, {
          at: payload.at,
          fieldId: payload.field_id,
          status: payload.status,
          text: "Обработка поля завершена",
        });
        setLogVersion((value) => value + 1);
      }
    });

    source.addEventListener("error", () => setConnected(false));

    return () => {
      source.close();
      setConnected(false);
    };
  }, [projectId, enabled]);

  return useMemo(() => {
    if (!snapshot) return { ...EMPTY, connected };

    // Снимок задаёт базу, события поверх него — свежие состояния стадий.
    const byField: Record<string, Record<number, StageState>> = {};
    for (const [fieldId, stages] of Object.entries(snapshot.fields)) {
      byField[fieldId] = Object.fromEntries(stages.map((stage) => [stage.stage_index, stage]));
    }
    for (const event of events) {
      const bucket = (byField[event.field_id] ??= {});
      bucket[event.stage_index] = {
        stage: event.stage,
        stage_title: event.stage_title,
        stage_index: event.stage_index,
        status: event.status,
        progress: event.progress,
        message: event.message,
        error: event.error,
      };
    }

    const stageTotal = snapshot.stage_total || snapshot.stages.length || 9;
    const progress: Record<string, FieldProgress> = {};
    for (const [fieldId, bucket] of Object.entries(byField)) {
      const stages = Object.values(bucket).sort((a, b) => a.stage_index - b.stage_index);
      progress[fieldId] = summarize(stages, stageTotal);
    }

    return {
      connected,
      stages: snapshot.stages,
      stageTotal,
      byField: progress,
      finished,
      log: logRef.current,
    };
    // logVersion участвует намеренно: лента живёт в ref, чтобы не пересоздавать
    // массив на каждое событие, но пересчёт мемо ей всё равно нужен.
  }, [snapshot, events, finished, connected, logVersion]);
}

function summarize(stages: StageState[], stageTotal: number): FieldProgress {
  const completed = stages.filter((stage) => stage.status === "done").length;
  const running = stages.find((stage) => stage.status === "running") ?? null;
  const failed = stages.some((stage) => stage.status === "failed");

  // Незавершённая стадия добавляет свою долю: без этого полоса стояла бы
  // на месте всё время работы длинной стадии сбора.
  const partial = running ? Math.min(Math.max(running.progress, 0), 1) : 0;
  const percent = Math.min(100, Math.round(((completed + partial) / stageTotal) * 100));

  return {
    stages,
    percent: failed ? Math.max(percent, 0) : percent,
    done: completed >= stageTotal,
    failed,
    current: running ?? stages[stages.length - 1] ?? null,
  };
}

function pushLog(ref: { current: ProgressState["log"] }, entry: ProgressState["log"][number]) {
  ref.current = [entry, ...ref.current].slice(0, MAX_LOG);
}
