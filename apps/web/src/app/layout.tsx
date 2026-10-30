import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Video2Robot · Perception workspace",
  description: "Inspect semantic action plans and identity-aware video perception.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
