"use client";

import * as React from "react";
import { Microphone, StopCircle } from "@phosphor-icons/react";

interface VoiceInputProps {
  language: string;
  disabled?: boolean;
  onInterimText: (text: string) => void;
  onFinalText: (text: string) => void;
}

interface SpeechRecognitionAlternativeLike {
  transcript: string;
}

interface SpeechRecognitionResultLike {
  isFinal: boolean;
  length: number;
  [index: number]: SpeechRecognitionAlternativeLike;
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: SpeechRecognitionResultLike;
  };
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

declare global {
  interface Window {
    webkitSpeechRecognition?: SpeechRecognitionCtor;
    SpeechRecognition?: SpeechRecognitionCtor;
  }
}

export function VoiceInput({ language, disabled, onInterimText, onFinalText }: VoiceInputProps) {
  const [active, setActive] = React.useState(false);
  const [supported, setSupported] = React.useState(true);
  const recognitionRef = React.useRef<SpeechRecognitionLike | null>(null);

  React.useEffect(() => {
    const Ctor = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    setSupported(!!Ctor);
  }, []);

  const stop = React.useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      recognitionRef.current = null;
    }
    onInterimText("");
    setActive(false);
  }, [onInterimText]);

  const start = React.useCallback(() => {
    const Ctor = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!Ctor) {
      setSupported(false);
      return;
    }

    const recognition = new Ctor();
    recognition.lang = language || "vi-VN";
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      let interim = "";
      let final = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const part = event.results[i][0]?.transcript ?? "";
        if (event.results[i].isFinal) {
          final += part;
        } else {
          interim += part;
        }
      }
      onInterimText(interim);
      if (final.trim()) {
        onFinalText(final.trim());
        onInterimText("");
      }
    };

    recognition.onerror = () => {
      stop();
    };

    recognition.onend = () => {
      stop();
    };

    recognitionRef.current = recognition;
    recognition.start();
    setActive(true);
  }, [language, onFinalText, onInterimText, stop]);

  return (
    <button
      type="button"
      title={supported ? (active ? "Stop voice input" : "Start voice input") : "Microphone is not supported"}
      disabled={disabled || !supported}
      onClick={active ? stop : start}
      className="inline-flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full border border-border bg-muted text-muted-foreground transition hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed md:h-10 md:w-10"
    >
      {active ? <StopCircle className="h-4 w-4 text-red-500" /> : <Microphone className="h-4 w-4" />}
    </button>
  );
}
