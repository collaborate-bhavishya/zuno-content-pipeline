import "./globals.css";
import type { Metadata } from "next";
import AuthGate from "../components/AuthGate";

export const metadata: Metadata = {
  title: "Zuno SpeakX — Lesson Pipeline",
  description: "Self-healing multi-agent lesson generator for early learners",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <AuthGate>{children}</AuthGate>
      </body>
    </html>
  );
}
