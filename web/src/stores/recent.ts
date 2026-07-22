import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface RecentStock {
  code: string;
  name: string;
  price: number;
  changePercent: number;
}

interface RecentState {
  stocks: RecentStock[];
  addStock: (stock: RecentStock) => void;
}

export const useRecentStore = create<RecentState>()(
  persist(
    (set, get) => ({
      stocks: [],
      addStock: (stock) => {
        const current = get().stocks;
        const filtered = current.filter((s) => s.code !== stock.code);
        set({ stocks: [stock, ...filtered].slice(0, 10) });
      },
    }),
    { name: 'recent-stocks' },
  ),
);