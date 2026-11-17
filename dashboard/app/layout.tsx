import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "Optical Test Health",
  description: "Ingestion health, measurement-system analysis, drift and instrument certification for a simulated optical test factory.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
