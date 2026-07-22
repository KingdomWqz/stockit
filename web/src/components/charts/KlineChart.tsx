'use client';

import { useEffect, useRef } from 'react';
import {
  createChart,
  type IChartApi,
  ColorType,
  CrosshairMode,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
} from 'lightweight-charts';
import type { KlineData } from '@/types/api';

interface KlineChartProps {
  data: KlineData[];
}

export default function KlineChart({ data }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#fff' },
        textColor: '#333',
      },
      grid: {
        vertLines: { color: '#f0f0f0' },
        horzLines: { color: '#f0f0f0' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#d1d4dc' },
      timeScale: { borderColor: '#d1d4dc', timeVisible: true },
      width: containerRef.current.clientWidth,
      height: 500,
    });

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#ef4444',
      downColor: '#22c55e',
      borderUpColor: '#ef4444',
      borderDownColor: '#22c55e',
      wickUpColor: '#ef4444',
      wickDownColor: '#22c55e',
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: '#26a69a',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });

    chart.priceScale('').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    // Calculate MAs
    const ma5 = calcMA(data, 5);
    const ma10 = calcMA(data, 10);
    const ma20 = calcMA(data, 20);
    const ma60 = calcMA(data, 60);

    const maConfigs: [ReturnType<typeof calcMA>, string, string][] = [
      [ma5, '#f5f5f5', '#f5f5f5'],
      [ma10, '#fbbf24', '#fbbf24'],
      [ma20, '#a855f7', '#a855f7'],
      [ma60, '#22c55e', '#22c55e'],
    ];

    const maColors = ['#f5f5f5', '#fbbf24', '#a855f7', '#22c55e'];

    const maSeries = maConfigs.map(([maData], i) => {
      const s = chart.addSeries(LineSeries, {
        color: maColors[i],
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      s.setData(maData);
      return s;
    });

    const candleData = data.map((d) => ({
      time: d.date as any,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }));

    const volData = data.map((d) => ({
      time: d.date as any,
      value: d.volume,
      color: d.close >= d.open ? 'rgba(239,68,68,0.5)' : 'rgba(34,197,94,0.5)',
    }));

    candlestickSeries.setData(candleData);
    volumeSeries.setData(volData);

    chartRef.current = chart;

    const resize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', resize);

    return () => {
      window.removeEventListener('resize', resize);
      chart.remove();
      chartRef.current = null;
    };
  }, [data]);

  return (
    <div
      ref={containerRef}
      className="w-full rounded border border-zinc-200 bg-white"
    />
  );
}

function calcMA(
  data: KlineData[],
  period: number,
): { time: string; value: number }[] {
  const result: { time: string; value: number }[] = [];
  for (let i = period - 1; i < data.length; i++) {
    let sum = 0;
    for (let j = 0; j < period; j++) {
      sum += data[i - j].close;
    }
    result.push({ time: data[i].date, value: sum / period });
  }
  return result;
}