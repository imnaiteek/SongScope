import type { Metadata } from "next";
import { Geist, Geist_Mono, Syne } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const syne = Syne({ variable: "--font-syne", subsets: ["latin"], weight: ["600", "700", "800"] });

export const metadata: Metadata = {
  title: "SongScope — Technical Music Analysis",
  description:
    "Upload a track or paste a YouTube link and uncover its tempo, key, chords, meter, structure and more.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} ${syne.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
