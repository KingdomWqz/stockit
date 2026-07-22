'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useStockSearch } from '@/hooks/use-stocks';
import { Loader2 } from 'lucide-react';

export default function StockSearch() {
  const [keyword, setKeyword] = useState('');
  const [debouncedKeyword, setDebouncedKeyword] = useState('');
  const [open, setOpen] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const { data: results, isLoading } = useStockSearch(debouncedKeyword);

  useEffect(() => {
    timerRef.current = setTimeout(() => {
      setDebouncedKeyword(keyword);
    }, 300);
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, [keyword]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleSelect = useCallback(
    (code: string) => {
      setOpen(false);
      setKeyword('');
      router.push(`/stocks/${code}`);
    },
    [router],
  );

  return (
    <div ref={wrapperRef} className="relative w-full max-w-md">
      <input
        type="text"
        value={keyword}
        onChange={(e) => {
          setKeyword(e.target.value);
          setOpen(true);
        }}
        onFocus={() => keyword && setOpen(true)}
        placeholder="搜索股票代码或名称..."
        className="w-full rounded border border-zinc-300 px-4 py-2 text-sm focus:border-blue-500 focus:outline-none"
      />

      {open && keyword && (
        <div className="absolute z-10 mt-1 w-full rounded border border-zinc-200 bg-white shadow-lg">
          {isLoading && (
            <div className="flex items-center justify-center py-4 text-sm text-zinc-400">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              搜索中...
            </div>
          )}

          {!isLoading && results && results.length === 0 && (
            <div className="py-4 text-center text-sm text-zinc-400">
              未找到匹配结果
            </div>
          )}

          {!isLoading &&
            results &&
            results.map((stock) => (
              <button
                key={stock.code}
                onClick={() => handleSelect(stock.code)}
                className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm hover:bg-zinc-50"
              >
                <span className="font-medium text-zinc-900">{stock.name}</span>
                <span className="text-zinc-400">{stock.code}</span>
                <span className="ml-auto rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-500">
                  {stock.market}
                </span>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}