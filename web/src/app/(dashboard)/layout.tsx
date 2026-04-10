import { headers } from "next/headers";

import SideNav from "@/components/SideNav";
import TopNav from "@/components/TopNav";
import { auth } from "../../../auth";
import { backend } from "@/lib/backend";

/**
 * Server-component shell used by every page under /candidates and /settings.
 *
 * Fetches app settings once so the sidebar can show the polling cadence and
 * the top bar can show the company name without each child page re-fetching.
 * If settings fetch fails (e.g. backend down), we degrade gracefully — the
 * pages will show their own error states.
 */
export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "localhost:3000";
  const proto = h.get("x-forwarded-proto") ?? "http";
  const baseUrl = `${proto}://${host}`;
  const cookieHeader = h.get("cookie") ?? undefined;

  // Defensive: middleware should already have redirected on a bad cookie,
  // but `auth()` can still throw JWTSessionError if the session cookie is
  // undecodable. Don't let that turn the whole dashboard into a 500.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let session: any = null;
  try {
    session = await auth();
  } catch {
    /* fall through — TopNav will render without an email */
  }

  // Best-effort settings fetch. The sidebar/topnav take defaults if the
  // backend is unreachable so the shell still renders and pages can show
  // their own errors — don't turn the whole dashboard into a 500 just
  // because /api/settings flaked.
  let companyName = "Plum";
  let pollingMinutes = 2;
  let lastPolledAt: string | null = null;
  try {
    const settings = await backend.getSettings({ baseUrl, cookieHeader });
    companyName = settings.company_name;
    pollingMinutes = settings.polling_minutes;
    lastPolledAt = settings.last_polled_at ?? null;
  } catch {
    /* fall through with defaults */
  }

  return (
    <div className="min-h-screen bg-surface">
      <SideNav pollingMinutes={pollingMinutes} lastPolledAt={lastPolledAt} />
      <TopNav companyName={companyName} userEmail={session?.user?.email ?? undefined} />
      <main className="ml-64 pt-28 px-12 pb-20">{children}</main>
    </div>
  );
}
