import Link from 'next/link';

export default function Header() {
  return (
    <header className="flex h-14 items-center justify-between border-b border-zinc-200 bg-white px-6">
      <Link href="/" className="text-lg font-bold text-zinc-900">
        Stockit
      </Link>
    </header>
  );
}
