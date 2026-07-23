import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Attest Guardian",
  description: "Evidence-first Tamil, Tanglish, and English document intelligence.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      {/*
        Browser extensions (e.g. Grammarly) inject attributes such as
        data-gr-ext-installed onto <body> before hydration. suppressHydrationWarning
        limits the mismatch check to this element only and does not hide real
        application markup differences.
      */}
      <body suppressHydrationWarning>
        <a className="skip-link" href="#main-content">
          Skip to main content
        </a>
        {children}
      </body>
    </html>
  );
}
