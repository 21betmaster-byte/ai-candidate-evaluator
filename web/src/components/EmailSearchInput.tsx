"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function EmailSearchInput({
  currentEmail,
  currentParams,
}: {
  currentEmail: string;
  currentParams: Record<string, string>;
}) {
  const [value, setValue] = useState(currentEmail);
  const router = useRouter();

  function navigate(email: string) {
    const params = new URLSearchParams();
    if (currentParams.level) params.set("level", currentParams.level);
    if (currentParams.step) params.set("step", currentParams.step);
    if (email) params.set("email", email);
    const qs = params.toString();
    router.push(`/logs${qs ? `?${qs}` : ""}`);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    navigate(value.trim());
  }

  function handleClear() {
    setValue("");
    navigate("");
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2">
      <div className="relative">
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Search by email…"
          className="bg-surface-container-lowest text-on-surface pl-4 pr-8 py-2 rounded-full text-xs font-label w-56 outline-none focus:ring-2 focus:ring-primary/30 placeholder:opacity-40"
        />
        {value && (
          <button
            type="button"
            onClick={handleClear}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-on-surface-variant opacity-40 hover:opacity-80 text-xs font-bold"
          >
            ✕
          </button>
        )}
      </div>
      <button
        type="submit"
        className="px-4 py-2 rounded-full text-xs font-bold uppercase tracking-wider bg-primary text-on-primary hover:opacity-90 transition-opacity"
      >
        Search
      </button>
    </form>
  );
}
