import type { Metadata } from "next";
import { Epilogue, Inter, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";

const epilogue = Epilogue({
  subsets: ["latin"],
  weight: ["400", "600", "700", "800", "900"],
  variable: "--font-epilogue",
  display: "swap",
});
const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-inter",
  display: "swap",
});
const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-jakarta",
  display: "swap",
});

export const metadata: Metadata = {
  title: "The Curator — Recruitment Intelligence",
  description: "AI-assisted candidate evaluation dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${epilogue.variable} ${inter.variable} ${jakarta.variable}`}>
      <head>
        {/* Material Symbols CDN — consistent with the stitch/ mocks. */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
        />
      </head>
      <body className="font-body bg-surface text-on-surface antialiased">{children}</body>
    </html>
  );
}
