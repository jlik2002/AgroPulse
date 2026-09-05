import type { EChartsOption } from "echarts";
import { useEffect, useRef } from "react";

import { echarts } from "@/components/charts/echarts";
import { cn } from "@/lib/cn";

interface EChartProps {
  option: EChartsOption;
  className?: string;
  height?: number | string;
  onEvents?: Record<string, (params: unknown) => void>;
}

export function EChart({ option, className, height = 280, onEvents }: EChartProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!hostRef.current) return;
    const chart = echarts.init(hostRef.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;

    // Размер графика зависит от раскладки карточки, а не окна: следим
    // за самим контейнером, иначе при сворачивании панели график остаётся широким.
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(hostRef.current);

    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    // notMerge: false сохраняет анимацию перехода при смене фильтров.
    chartRef.current?.setOption(option, { notMerge: true, lazyUpdate: true });
  }, [option]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !onEvents) return;
    for (const [name, handler] of Object.entries(onEvents)) chart.on(name, handler);
    return () => {
      for (const [name, handler] of Object.entries(onEvents)) chart.off(name, handler);
    };
  }, [onEvents]);

  return (
    <div
      ref={hostRef}
      className={cn("w-full", className)}
      style={{ height: typeof height === "number" ? `${height}px` : height }}
    />
  );
}
