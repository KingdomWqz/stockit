'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { useStockSnapshot, useKlineData } from '@/hooks/use-stocks';
import { useRecentStore } from '@/stores/recent';
import KlineChart from '@/components/charts/KlineChart';
import PeriodSelector from '@/components/stock/PeriodSelector';
import StockHeader from '@/components/stock/StockHeader';

export default function StockPage() {
  const params = useParams();
  const code = params.code as string;
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('day');

  const { data: snapshot, isLoading, isError } = useStockSnapshot(code);
  const { data: klineData } = useKlineData(code, period);
  const addStock = useRecentStore((s) => s.addStock);

  useEffect(() => {
    if (snapshot) {
      addStock({
        code: snapshot.code,
        name: snapshot.name,
        price: snapshot.price,
        changePercent: snapshot.changePercent,
      });
    }
  }, [snapshot, addStock]);

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <StockHeader snapshot={snapshot} isLoading={isLoading} isError={isError} />

      <div className="mt-4 flex items-center justify-between">
        <PeriodSelector period={period} onChange={setPeriod} />
      </div>

      <div className="mt-4">
        {klineData ? (
          <KlineChart data={klineData} />
        ) : (
          <div className="flex h-[500px] items-center justify-center rounded border border-zinc-200 bg-white">
            <p className="text-sm text-zinc-400">加载K线数据...</p>
          </div>
        )}
      </div>
    </div>
  );
}