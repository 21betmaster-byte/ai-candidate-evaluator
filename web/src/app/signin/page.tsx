import { redirect } from "next/navigation";

import { signIn } from "../../../auth";

/**
 * Email + password sign-in backed by the Credentials provider in auth.ts.
 * Renders a server-action form so we don't need to ship `next-auth/react`
 * to the client just to post creds.
 */
export default function SignIn({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; error?: string }>;
}) {
  async function doSignIn(formData: FormData) {
    "use server";
    const email = formData.get("email")?.toString() ?? "";
    const password = formData.get("password")?.toString() ?? "";
    try {
      // redirect:false -> we handle the redirect ourselves on success.
      await signIn("credentials", { email, password, redirect: false });
    } catch {
      // Auth.js throws on invalid creds; surface a friendly error via query.
      redirect(`/signin?error=1`);
    }
    redirect("/candidates");
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-surface">
      <form
        action={doSignIn}
        className="bg-surface-container-lowest p-12 rounded-xl shadow-editorial max-w-md w-full flex flex-col gap-6"
      >
        <AsyncHiddenFrom searchParams={searchParams} />
        <div>
          <h1 className="font-headline text-4xl font-black tracking-tighter">The Curator</h1>
          <p className="text-on-surface-variant mt-2 text-sm">
            Recruitment Intelligence · Internal dashboard sign-in.
          </p>
        </div>

        <AsyncError searchParams={searchParams} />

        <div>
          <label
            htmlFor="signin-email"
            className="block text-[10px] font-label font-bold text-on-surface-variant uppercase tracking-widest mb-2"
          >
            Email
          </label>
          <input
            id="signin-email"
            name="email"
            type="email"
            required
            defaultValue="admin@curator.local"
            className="w-full bg-surface-container-lowest border-0 border-b-2 border-outline-variant focus:ring-0 focus:border-primary py-2 text-sm font-medium"
          />
        </div>

        <div>
          <label
            htmlFor="signin-password"
            className="block text-[10px] font-label font-bold text-on-surface-variant uppercase tracking-widest mb-2"
          >
            Password
          </label>
          <input
            id="signin-password"
            name="password"
            type="password"
            required
            defaultValue="curator"
            className="w-full bg-surface-container-lowest border-0 border-b-2 border-outline-variant focus:ring-0 focus:border-primary py-2 text-sm font-medium"
          />
        </div>

        <button
          type="submit"
          className="bg-gradient-to-br from-primary to-primary/80 text-on-primary py-4 rounded-full font-headline font-black text-sm shadow-[0_4px_14px_rgba(255,71,87,0.3)] hover:brightness-110 active:scale-95 transition-all"
        >
          Sign in
        </button>

        <div className="text-[11px] opacity-60 font-mono bg-surface-container-low p-3 rounded-lg">
          <p className="font-bold mb-1">Test credentials</p>
          <p>admin@curator.local / curator</p>
          <p>shivam@curator.local / curator</p>
          <p className="mt-2 opacity-70">Edit users in web/auth.ts.</p>
        </div>
      </form>
    </main>
  );
}

async function AsyncHiddenFrom({
  searchParams,
}: {
  searchParams: Promise<{ from?: string }>;
}) {
  const sp = await searchParams;
  return <input type="hidden" name="from" value={sp?.from ?? "/candidates"} />;
}

async function AsyncError({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const sp = await searchParams;
  if (!sp?.error) return null;
  return (
    <p className="text-xs text-error bg-error-container/60 p-3 rounded-lg">
      Invalid email or password. Check the test credentials below.
    </p>
  );
}
