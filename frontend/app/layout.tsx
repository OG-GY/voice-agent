import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "The Copper Pot · Voice reservations",
  description: "Call The Copper Pot's voice receptionist to book or cancel a table.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
