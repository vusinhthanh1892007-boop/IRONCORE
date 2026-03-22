"use client";

export interface UserSettings {
  displayName: string;
  language: string;
  timezone: string;
  defaultModel: string;
  apiProvider: string;
  temperature: number;
  maxTokens: number;
  theme: "dark" | "light" | "system";
  fontSize: "sm" | "md" | "lg";
  logLevel: "DEBUG" | "INFO" | "WARNING" | "ERROR";
  cacheEnabled: boolean;
  compressionEnabled: boolean;
}

export const USER_SETTINGS_KEY = "ironcore_settings";
export const USER_SETTINGS_EVENT = "ironcore:user-settings-changed";

export const defaultUserSettings: UserSettings = {
  displayName: "User Name",
  language: "en",
  timezone: "Asia/Ho_Chi_Minh",
  defaultModel: "qwen2.5:7b",
  apiProvider: "ollama",
  temperature: 0.4,
  maxTokens: 2048,
  theme: "dark",
  fontSize: "md",
  logLevel: "INFO",
  cacheEnabled: true,
  compressionEnabled: true,
};

export function normalizeLanguage(value: string) {
  return value.trim().toLowerCase() || "en";
}

export function readUserSettings(): UserSettings {
  if (typeof window === "undefined") {
    return defaultUserSettings;
  }

  try {
    const stored = window.localStorage.getItem(USER_SETTINGS_KEY);
    if (!stored) return defaultUserSettings;
    const parsed = JSON.parse(stored);
    return {
      ...defaultUserSettings,
      ...parsed,
      language: normalizeLanguage(
        parsed.language ?? defaultUserSettings.language
      ),
    };
  } catch {
    return defaultUserSettings;
  }
}

export function writeUserSettings(settings: UserSettings) {
  if (typeof window === "undefined") return;

  const next = {
    ...settings,
    language: normalizeLanguage(settings.language),
  };
  window.localStorage.setItem(USER_SETTINGS_KEY, JSON.stringify(next));
  window.dispatchEvent(
    new CustomEvent(USER_SETTINGS_EVENT, {
      detail: next,
    })
  );
}
