import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Valoscribe Studio",
  description: "Offline, evidence-backed VALORANT VOD analysis.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
