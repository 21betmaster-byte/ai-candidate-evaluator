"use client";
/**
 * Sidebar, extracted from the stitch/system_configuration mock. Client
 * component because it needs usePathname() to highlight the active
 * section and because Poll Now is interactive. Sign-out uses Auth.js's
 * built-in /api/auth/signout endpoint so we don't need a server action
 * here.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import PollNowButton from "./PollNowButton";

const BASE = "flex items-center gap-4 py-3 px-6 transition-all duration-300";
const ACTIVE = `text-primary font-extrabold bg-surface-container-lowest rounded-r-full ${BASE}`;
const INACTIVE = `text-on-surface/60 hover:text-primary ${BASE}`;

export default function SideNav({ pollingMinutes }: { pollingMinutes: number }) {
  const path = usePathname() ?? "";
  const isSettings = path.startsWith("/settings");

  return (
    <aside className="bg-surface-container-low h-screen w-64 fixed left-0 top-0 overflow-y-auto flex flex-col py-8 space-y-8 z-40">
      <div className="px-8">
        <h1 className="text-xl font-black uppercase tracking-widest font-headline">The Curator</h1>
        <p className="text-[10px] uppercase tracking-[0.2em] opacity-60 font-bold mt-1">
          Recruitment Intelligence
        </p>
      </div>

      <nav className="flex-1 space-y-2">
        <Link href="/candidates" className={!isSettings ? ACTIVE : INACTIVE}>
          <span className="material-symbols-outlined">group</span>
          <span className="font-headline font-bold tracking-tight text-sm">Candidates</span>
        </Link>
        <Link href="/settings" className={isSettings ? ACTIVE : INACTIVE}>
          <span className="material-symbols-outlined">settings</span>
          <span className="font-headline font-bold tracking-tight text-sm">Settings</span>
        </Link>
      </nav>

      <div className="px-6 space-y-6">
        <PollNowButton pollingMinutes={pollingMinutes} />
        <a
          href="/api/auth/signout"
          className="text-on-surface/60 flex items-center gap-4 py-2 px-2 hover:text-primary transition-all text-xs font-semibold border-t border-outline-variant/10 pt-4"
        >
          <span className="material-symbols-outlined text-sm">logout</span>
          Sign out
        </a>
      </div>
    </aside>
  );
}
