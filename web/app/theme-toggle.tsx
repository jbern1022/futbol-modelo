"use client";

import { useEffect, useState } from "react";

export default function ThemeToggle() {
  const [isDark, setIsDark] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // One-time read of DOM state an inline script already set before
    // hydration (flash-of-wrong-theme prevention) -- has to happen in
    // an effect, not during render, since it must run only after
    // mount to avoid a server/client markup mismatch (document doesn't
    // exist during SSR). This is exactly the "synchronizing with an
    // external system" case React's own docs say an effect is for
    // (https://react.dev/learn/you-might-not-need-an-effect), not the
    // "derived state" anti-pattern react-hooks/set-state-in-effect
    // otherwise (correctly, elsewhere) guards against.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true);
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !isDark;
    setIsDark(next);
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("theme", next ? "dark" : "light");
  }

  if (!mounted) {
    return <div className="h-8 w-8" />;
  }

  return (
    <button onClick={toggle} aria-label="Toggle dark mode" className="flex h-9 w-9 items-center justify-center rounded-full border border-zinc-300 bg-white text-zinc-700 shadow-md hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700">
      {isDark ? "\u2600" : "\u263D"}
    </button>
  );
}
