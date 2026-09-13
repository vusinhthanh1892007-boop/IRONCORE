export interface LanguageOption {
  code: string;
  label: string;
}

const SUPPORTED_LANGUAGES: Record<string, string> = {
  "en": "English", "vi": "Tiếng Việt", "zh": "中文", "ja": "日本語",
  "fr": "Français", "de": "Deutsch", "es": "Español", "it": "Italiano",
  "ko": "한국어", "ru": "Русский", "pt": "Português", "ar": "العربية",
  "hi": "हिन्दी", "id": "Bahasa Indonesia", "th": "ไทย", "nl": "Nederlands",
  "tr": "Türkçe", "pl": "Polski", "sv": "Svenska", "cs": "Čeština",
  "el": "Ελληνικά", "ro": "Română", "hu": "Magyar", "uk": "Українська",
  "bn": "বাংলা", "he": "עברית", "ta": "தமிழ்", "ur": "اردو",
  "fa": "فارسی", "ms": "Bahasa Melayu"
};

export function buildLanguageOptions(_displayLocale = "en"): LanguageOption[] {
  return Object.entries(SUPPORTED_LANGUAGES).map(([code, name]) => ({
    code,
    label: `${name} (${code})`
  }));
}
