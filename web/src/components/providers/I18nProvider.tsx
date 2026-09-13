"use client";

import * as React from "react";
import type { LanguageOption } from "@/lib/languages";

interface I18nContextValue {
  language: string;
  setLanguage: (code: string) => void;
  options: LanguageOption[];
}

const I18nContext = React.createContext<I18nContextValue | null>(null);
export function I18nProvider({ children }: { children: React.ReactNode }) {
  const options = React.useMemo<LanguageOption[]>(() => [{ code: "en", label: "English (en)" }], []);
  const setLanguage = React.useCallback(() => {}, []);

  React.useEffect(() => {
    document.documentElement.lang = "en";
  }, []);

  return <I18nContext.Provider value={{ language: "en", setLanguage, options }}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = React.useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
