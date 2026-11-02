import type { ReactNode } from "react";

/**
 * Minimal layout for auth pages: no navbar, no command palette. Mirrors the
 * chrome of <AuthLayout/> so /login feels like the same family as
 * /signup, /forgot-password, /reset-password (same vertical rhythm,
 * same Terms/Privacy footer rail).
 */
export default function LoginLayout({ children }: { children: ReactNode }) {
  return (
    <div className="auth-content min-h-screen bg-paper bg-paper-grain">
      <div className="min-h-screen flex flex-col items-center px-6 py-10">
        <div className="w-full max-w-md flex-1 flex flex-col justify-center">
          {children}
        </div>
        <footer className="mt-10 flex items-center gap-5 font-sans text-[12px] text-graphite-soft">
          <a href="https://papercrane.bio/terms" className="hover:text-ink">
            Terms
          </a>
          <a href="https://papercrane.bio/privacy" className="hover:text-ink">
            Privacy
          </a>
          <a href="https://papercrane.bio" className="hover:text-ink">
            papercrane.bio
          </a>
        </footer>
      </div>
    </div>
  );
}
