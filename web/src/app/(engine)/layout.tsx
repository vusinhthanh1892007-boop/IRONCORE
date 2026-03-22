import type { ReactNode } from "react";
import { EngineLayout } from "@/components/layout/EngineLayout";

export default function EngineRootLayout({ children }: { children: ReactNode }) {
  return <EngineLayout>{children}</EngineLayout>;
}
