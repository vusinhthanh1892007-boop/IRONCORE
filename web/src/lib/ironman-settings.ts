export type GestureKey = "thumbs_up" | "fist" | "open_hand" | "peace" | "point_up";

export type IronManAction =
  | "approve_hitl"
  | "stop_stream"
  | "clear_input"
  | "new_session"
  | "submit_input"
  | "none";

export interface IronManSettings {
  cameraEnabled: boolean;
  gestureEnabled: boolean;
  voiceEnabled: boolean;
  sttLanguage: string;
  gestureSensitivity: number;
  testMode: boolean;
  gestureMap: Record<GestureKey, IronManAction>;
  enabledGestures: Record<GestureKey, boolean>;
}

export const IRONMAN_SETTINGS_KEY = "ironcore_ironman_settings";
export const IRONMAN_SETTINGS_EVENT = "ironcore:ironman-settings-changed";

export const defaultIronManSettings: IronManSettings = {
  cameraEnabled: false,
  gestureEnabled: false,
  voiceEnabled: false,
  sttLanguage: "vi-VN",
  gestureSensitivity: 0.6,
  testMode: false,
  gestureMap: {
    thumbs_up: "approve_hitl",
    fist: "stop_stream",
    open_hand: "clear_input",
    peace: "new_session",
    point_up: "submit_input",
  },
  enabledGestures: {
    thumbs_up: true,
    fist: true,
    open_hand: true,
    peace: true,
    point_up: true,
  },
};

export function getIronManSettings(): IronManSettings {
  if (typeof window === "undefined") return defaultIronManSettings;
  try {
    const raw = window.localStorage.getItem(IRONMAN_SETTINGS_KEY);
    if (!raw) return defaultIronManSettings;
    const parsed = JSON.parse(raw) as Partial<IronManSettings>;
    return {
      ...defaultIronManSettings,
      ...parsed,
      gestureMap: {
        ...defaultIronManSettings.gestureMap,
        ...(parsed.gestureMap ?? {}),
      },
      enabledGestures: {
        ...defaultIronManSettings.enabledGestures,
        ...(parsed.enabledGestures ?? {}),
      },
    };
  } catch {
    return defaultIronManSettings;
  }
}

export function saveIronManSettings(next: IronManSettings) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(IRONMAN_SETTINGS_KEY, JSON.stringify(next));
  window.dispatchEvent(new CustomEvent(IRONMAN_SETTINGS_EVENT, { detail: next }));
}
