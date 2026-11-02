"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV } from "@/lib/nav";
import { clsx } from "clsx";

export function Sidebar() {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-8 py-10 pr-6 text-[14px] text-ink-soft">
      {NAV.map((section) => (
        <div key={section.title}>
          <div className="eyebrow mb-3 text-graphite">{section.title}</div>
          <ul className="flex flex-col gap-1">
            {section.items.map((item) => {
              const active = pathname === item.href;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className={clsx(
                      "block rounded-md px-2 py-1.5 transition-colors",
                      active
                        ? "bg-paper-fold text-ink font-medium"
                        : "hover:bg-paper-fold/60 hover:text-ink",
                    )}
                  >
                    {item.title}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
