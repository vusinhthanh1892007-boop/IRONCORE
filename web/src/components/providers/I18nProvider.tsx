"use client";

import * as React from "react";
import { buildLanguageOptions, type LanguageOption } from "@/lib/languages";
import {
  readUserSettings,
  writeUserSettings,
} from "@/lib/user-settings";

interface I18nContextValue {
  language: string;
  setLanguage: (code: string) => void;
  options: LanguageOption[];
}

const I18N_KEY = "ironcore_ui_language";
const textCache = new Map<string, string>();
const originalText = new WeakMap<Text, string>();
const originalPlaceholder = new WeakMap<HTMLElement, string>();

const I18nContext = React.createContext<I18nContextValue | null>(null);

function batch<T>(items: T[], size = 24) {
  const rows: T[][] = [];
  for (let i = 0; i < items.length; i += size) rows.push(items.slice(i, i + size));
  return rows;
}

function normalizedCode(code: string) {
  const value = code.trim().toLowerCase().replace(/_/g, "-");
  if (!value) return "en";
  return value.split("-")[0] || "en";
}

function collectTextNodes(root: ParentNode): Text[] {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let current = walker.nextNode();
  while (current) {
    const textNode = current as Text;
    const value = textNode.nodeValue?.trim() ?? "";
    const parent = textNode.parentElement;

    if (
      parent &&
      value.length >= 2 &&
      value.length <= 160 &&
      !/^[\d\s~`!@#$%^&*()_+\-={}\[\]:;"'<>?,./|\\]+$/.test(value) &&
      !["SCRIPT", "STYLE", "CODE", "PRE", "NOSCRIPT"].includes(parent.tagName)
    ) {
      nodes.push(textNode);
    }

    current = walker.nextNode();
  }
  return nodes;
}

async function translateTexts(texts: string[], target: string): Promise<string[]> {
  if (target === "en") return texts;
  const uncached = texts.filter((item) => !textCache.has(`${target}:${item}`));

  for (const chunk of batch(uncached, 18)) {
    const res = await fetch("/api/i18n/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texts: chunk, source: "en", target }),
    });
    const payload = (await res.json().catch(() => ({ translations: chunk }))) as {
      translations?: string[];
    };
    const rows = payload.translations ?? chunk;
    chunk.forEach((sourceText, idx) => {
      textCache.set(`${target}:${sourceText}`, rows[idx] || sourceText);
    });
  }

  return texts.map((item) => textCache.get(`${target}:${item}`) || item);
}

function restoreDocument() {
  const nodes = collectTextNodes(document.body);
  for (const node of nodes) {
    const original = originalText.get(node);
    if (original) node.nodeValue = original;
  }

  const placeholders = document.querySelectorAll<HTMLElement>("input[placeholder], textarea[placeholder], button[title], [aria-label]");
  placeholders.forEach((el) => {
    const original = originalPlaceholder.get(el);
    if (!original) return;
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      el.placeholder = original;
      return;
    }
    if (el instanceof HTMLButtonElement) {
      el.title = original;
      return;
    }
    el.setAttribute("aria-label", original);
  });
}

async function translateDocument(target: string) {
  if (target === "en") {
    restoreDocument();
    return;
  }

  const nodes = collectTextNodes(document.body);
  const sourceTexts = nodes.map((node) => {
    const value = node.nodeValue ?? "";
    if (!originalText.has(node)) originalText.set(node, value);
    return originalText.get(node) ?? value;
  });

  const translated = await translateTexts(sourceTexts, target);
  nodes.forEach((node, idx) => {
    node.nodeValue = translated[idx] || sourceTexts[idx];
  });

  const attrs = document.querySelectorAll<HTMLElement>("input[placeholder], textarea[placeholder], button[title], [aria-label]");
  const values = Array.from(attrs).map((el) => {
    let base = "";
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) base = el.placeholder;
    else if (el instanceof HTMLButtonElement) base = el.title;
    else base = el.getAttribute("aria-label") ?? "";
    if (!originalPlaceholder.has(el)) originalPlaceholder.set(el, base);
    return originalPlaceholder.get(el) ?? base;
  });

  const translatedAttrs = await translateTexts(values, target);
  attrs.forEach((el, idx) => {
    const value = translatedAttrs[idx] || values[idx];
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      el.placeholder = value;
      return;
    }
    if (el instanceof HTMLButtonElement) {
      el.title = value;
      return;
    }
    el.setAttribute("aria-label", value);
  });
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [language, setLanguageState] = React.useState("en");
  const [options, setOptions] = React.useState<LanguageOption[]>(() => [{ code: "en", label: "English (en)" }]);
  const translateTimer = React.useRef<number | null>(null);

  React.useEffect(() => {
    try {
      const userSettings = readUserSettings();
      const stored = localStorage.getItem(I18N_KEY);
      const initial = normalizedCode(
        stored || userSettings.language || navigator.language.split("-")[0] || "en"
      );
      setLanguageState(initial);
    } catch {
      setLanguageState("en");
    }

    try {
      const displayLocale = navigator.language || "en";
      setOptions(buildLanguageOptions(displayLocale));
    } catch {
      setOptions(buildLanguageOptions("en"));
    }
  }, []);

  const setLanguage = React.useCallback((code: string) => {
    const next = normalizedCode(code);
    setLanguageState(next);
    localStorage.setItem(I18N_KEY, next);
    const existing = readUserSettings();
    writeUserSettings({ ...existing, language: next });
  }, []);

  React.useEffect(() => {
    document.documentElement.lang = language;

    const scheduleTranslate = () => {
      if (translateTimer.current) {
        window.clearTimeout(translateTimer.current);
      }
      translateTimer.current = window.setTimeout(() => {
        void translateDocument(language);
      }, 120);
    };

    scheduleTranslate();

    const observer = new MutationObserver(() => {
      scheduleTranslate();
    });
    observer.observe(document.body, { childList: true, subtree: true });

    return () => {
      if (translateTimer.current) {
        window.clearTimeout(translateTimer.current);
        translateTimer.current = null;
      }
      observer.disconnect();
    };
  }, [language]);

  return <I18nContext.Provider value={{ language, setLanguage, options }}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = React.useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
