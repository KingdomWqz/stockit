'use client';

import StockSearch from '@/components/stock/StockSearch';
import { useRecentStore } from '@/stores/recent';
import Link from 'next/link';

export default function Home() {
  const recentStocks = useRecentStore((s) => s.stocks);

  return (
    <div className="flex flex-col items-center px-4 py-16">
      <h1 className="mb-8 text-2xl font-bold text-zinc-900">Stockit</h1>
      <StockSearch />

      {recentStocks.length > 0 && (
        <div className="mt-12 w-full max-w-md">
          <h2 className="mb-3 text-sm font-medium text-zinc-500">最近查看</h2>
          <div className="space-y-2">
            {recentStocks.map((stock) => {
              const isUp = stock.changePercent >= 0;
              const color = isUp ? 'text-red-600' : 'text-green-600';
              return (
                <Link
                  key={stock.code}
                  href={`/stocks/${stock.code}`}
                  className="flex items-center justify-between rounded-lg border border-zinc-200 px-4 py-3 hover:bg-zinc-50"
                >
                  <div>
                    <span className="font-medium text-zinc-900">{stock.name}</span>
                    <span className="ml-2 text-sm text-zinc-400">{stock.code}</span>
                  </div>
                  <div className="text-right">
                    <span className={`block text-sm font-medium ${color}`}>
                      {stock.price.toFixed(2)}
                    </span>
                    <span className={`text-xs ${color}`}>
                      {isUp ? '+' : ''}{stock.changePercent.toFixed(2)}%
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      )}

      {recentStocks.length === 0 && (
        <p className="mt-12 text-sm text-zinc-400">搜索股票开始使用</p>
      )}
    </div>
  );
}