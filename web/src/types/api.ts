export interface StockSearchResult {
  code: string;
  name: string;
  market: string;
}

export interface StockSnapshot {
  code: string;
  name: string;
  market: string;
  price: number;
  change: number;
  changePercent: number;
  high: number;
  low: number;
  open: number;
  volume: number;
  turnover: number;
}

export interface KlineData {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}