import { headers } from "next/headers";

import SettingsForm from "@/components/SettingsForm";
import { backend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "localhost:3000";
  const proto = h.get("x-forwarded-proto") ?? "http";
  const baseUrl = `${proto}://${host}`;
  const cookieHeader = h.get("cookie") ?? undefined;

  let error: string | null = null;
  let initial = null;
  try {
    initial = await backend.getSettings({ baseUrl, cookieHeader });
  } catch (err) {
    error = (err as Error).message;
  }

  return (
    <>
      <header className="mb-12">
        <h1 className="font-headline text-5xl font-black tracking-tighter mb-2 italic">
          Intelligence Core
        </h1>
        <p className="text-on-surface-variant max-w-xl font-label text-sm uppercase tracking-widest opacity-70">
          Define the logic. Calibrate the editorial eye. Automation with authority.
        </p>
      </header>

      {error || !initial ? (
        <div className="bg-surface-container-lowest p-10 rounded-xl shadow-editorial-soft">
          <p className="font-headline text-xl font-bold">Couldn't load settings</p>
          <p className="text-sm opacity-60 mt-2">{error ?? "unknown error"}</p>
        </div>
      ) : (
        <SettingsForm initial={initial} />
      )}
    </>
  );
}
