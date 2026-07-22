'use client';

import type { StockSnapshot } from '@/types/api';

interface StockHeaderProps {
  snapshot: StockSnapshot | undefined;
  isLoading: boolean;
  isError: boolean;
}

export default function StockHeader({ snapshot, isLoading, isError }: StockHeaderProps) {
  if (isLoading) {
    return (
      <div className="animate-pulse space-y-2">
        <div className="h-6 w-32 rounded bg-zinc-200" />
        <div className="h-8 w-40 rounded bg-zinc-200" />
      </div>
    );
  }

  if (isError || !snapshot) {
    return <p className="text-sm text-zinc-500">加载失败</p>;
  }

  const isUp = snapshot.change >= 0;
  const color = isUp ? 'text-red-600' : 'text-green-600';

  return (
    <div>
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-bold text-zinc-900">{snapshot.name}</h1>
        <span className="text-sm text-zinc-400">{snapshot.code}</span>
        <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-500">
          {snapshot.market}
        </span>
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className={`text-2xl font-semibold ${color}`}>
          {snapshot.price.toFixed(2)}
        </span>
        <span className={`text-sm ${color}`}>
          {isUp ? '+' : ''}{snapshot.change.toFixed(2)}
        </span>
        <span className={`text-sm ${color}`}>
          {isUp ? '+' : ''}{snapshot.changePercent.toFixed(2)}%
        </span>
      </div>
    </div>
  );
}