import type { ReactNode } from "react";
import { LinearLayout } from "@/components/layout/LinearLayout";

export default function AppLayout({ children }: { children: ReactNode }) {
  return <LinearLayout>{children}</LinearLayout>;
}
