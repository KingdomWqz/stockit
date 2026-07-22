'use client';

import Link from 'next/link';
import { useAuthStore } from '@/stores/auth';
import { useRouter } from 'next/navigation';

export default function Header() {
  const token = useAuthStore((s) => s.token);
  const logout = useAuthStore((s) => s.logout);
  const router = useRouter();

  const handleLogout = () => {
    logout();
    document.cookie = 'token=; path=/; max-age=0';
    router.push('/login');
  };

  return (
    <header className="flex h-14 items-center justify-between border-b border-zinc-200 bg-white px-6">
      <Link href="/" className="text-lg font-bold text-zinc-900">
        Stockit
      </Link>
      {token && (
        <button
          onClick={handleLogout}
          className="text-sm text-zinc-500 hover:text-zinc-700"
        >
          退出
        </button>
      )}
    </header>
  );
}