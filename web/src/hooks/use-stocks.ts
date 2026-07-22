import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { StockSearchResult, StockSnapshot, KlineData } from '@/types/api';

export function useStockSearch(keyword: string) {
  return useQuery({
    queryKey: ['stock-search', keyword],
    queryFn: async () => {
      const res = await api.get<StockSearchResult[]>('/stocks/search', {
        params: { keyword },
      });
      return res.data;
    },
    enabled: keyword.length > 0,
    staleTime: 60_000,
  });
}

export function useStockSnapshot(code: string) {
  return useQuery({
    queryKey: ['stock-snapshot', code],
    queryFn: async () => {
      const res = await api.get<StockSnapshot>(`/stocks/${code}`);
      return res.data;
    },
    enabled: !!code,
    staleTime: 10_000,
  });
}

export function useKlineData(code: string, period: 'day' | 'week' | 'month') {
  return useQuery({
    queryKey: ['kline-data', code, period],
    queryFn: async () => {
      const res = await api.get<KlineData[]>(`/stocks/${code}/kline`, {
        params: { period },
      });
      return res.data;
    },
    enabled: !!code,
    staleTime: 60_000,
  });
}