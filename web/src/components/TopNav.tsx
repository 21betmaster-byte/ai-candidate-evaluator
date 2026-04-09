/**
 * Top navigation bar. Shows the company name + user email. The mocks show
 * a role switcher and "New Role" button, but since we only have one role
 * right now, we render a simple brand + user strip.
 */
export default function TopNav({
  companyName,
  userEmail,
}: {
  companyName: string;
  userEmail: string | null | undefined;
}) {
  const initials = (userEmail ?? "??")
    .split("@")[0]
    .slice(0, 2)
    .toUpperCase();

  return (
    <header className="fixed top-0 right-0 w-[calc(100%-16rem)] z-30 bg-surface/80 backdrop-blur-md shadow-editorial-soft flex justify-between items-center px-12 py-6">
      <div className="flex items-center gap-8">
        <div>
          <span className="text-[10px] uppercase tracking-widest opacity-50 font-bold">
            {companyName}
          </span>
          <h2 className="font-headline text-lg font-black">Recruitment Intelligence</h2>
        </div>
      </div>
      <div className="flex items-center gap-6">
        <div
          className="w-10 h-10 rounded-full bg-primary text-on-primary flex items-center justify-center font-headline font-black text-sm"
          title={userEmail ?? undefined}
        >
          {initials}
        </div>
      </div>
    </header>
  );
}
