import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { NavLink } from "@/components/nav-link";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Flaky Debug Agent",
  description: "Monitoring dashboard for LangGraph flaky-test debugging runs",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`dark ${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col bg-black text-ink">
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
            <div className="flex items-center gap-5">
              <Link href="/" className="font-semibold text-ink transition-colors hover:text-accent-strong">
                Flaky Debug Agent
              </Link>
              <nav className="flex items-center gap-4 text-sm">
                <NavLink href="/runs">Runs</NavLink>
                <Link
                  href="/demo"
                  className="inline-flex items-center gap-2 rounded-full bg-emerald-600 px-3.5 py-1.5 font-medium text-white shadow-sm ring-1 ring-emerald-700/20 transition-colors hover:bg-emerald-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-600 dark:bg-emerald-500 dark:ring-emerald-400/30 dark:hover:bg-emerald-400 dark:hover:text-zinc-950"
                >
                  <span className="relative flex size-2">
                    <span className="absolute inline-flex size-full animate-ping rounded-full bg-white/80" />
                    <span className="relative inline-flex size-2 rounded-full bg-white" />
                  </span>
                  Live Demo
                </Link>
              </nav>
            </div>
            <span className="text-xs text-ink-faint">LangGraph run monitor</span>
          </div>
        </header>
        <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
