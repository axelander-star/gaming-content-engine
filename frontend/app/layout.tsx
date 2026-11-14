import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AuthProvider } from "@/components/AuthProvider";

import "./globals.css";

export const metadata: Metadata = {
  title: "Gaming Content Engine",
  description: "Steuerung der Gaming Content Engine",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="de">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
