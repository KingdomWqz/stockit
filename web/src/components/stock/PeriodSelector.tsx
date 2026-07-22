'use client';

interface PeriodSelectorProps {
  period: 'day' | 'week' | 'month';
  onChange: (period: 'day' | 'week' | 'month') => void;
}

const LABELS: Record<'day' | 'week' | 'month', string> = {
  day: '日K',
  week: '周K',
  month: '月K',
};

export default function PeriodSelector({ period, onChange }: PeriodSelectorProps) {
  return (
    <div className="flex gap-1">
      {(['day', 'week', 'month'] as const).map((p) => (
        <button
          key={p}
          onClick={() => onChange(p)}
          className={`rounded px-3 py-1 text-sm font-medium transition-colors ${
            period === p
              ? 'bg-blue-600 text-white'
              : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200'
          }`}
        >
          {LABELS[p]}
        </button>
      ))}
    </div>
  );
}