"use client";

import * as React from "react";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Paperclip, PaperPlaneTilt as Send, Square } from "@phosphor-icons/react";
import { useDropzone } from "react-dropzone";
import type { Attachment } from "@/store/chat-store";
import { VoiceInput } from "@/components/ironman/VoiceInput";
import {
  getIronManSettings,
  IRONMAN_SETTINGS_EVENT,
  type IronManSettings,
} from "@/lib/ironman-settings";

interface InputBarProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  isStreaming: boolean;
  attachments: Attachment[];
  onAddFiles: (files: File[]) => void;
  onRemoveFile: (id: string) => void;
}

export function InputBar({
  value,
  onChange,
  onSend,
  onStop,
  isStreaming,
  attachments,
  onAddFiles,
  onRemoveFile,
}: InputBarProps) {
  const inputRef = React.useRef<HTMLTextAreaElement | null>(null);
  const [interimTranscript, setInterimTranscript] = React.useState("");
  const [ironManSettings, setIronManSettings] = React.useState<IronManSettings>(() => getIronManSettings());
  const { getRootProps, getInputProps, isDragActive, open: openFilePicker } = useDropzone({
    disabled: isStreaming,
    noClick: true,
    multiple: true,
    onDrop: onAddFiles,
    maxSize: 10 * 1024 * 1024,
    accept: {
      "image/*": [],
      "application/pdf": [],
      "text/plain": [],
      "text/markdown": [".md"],
      "application/javascript": [".js"],
      "text/x-python": [".py"],
      "text/typescript": [".ts"],
    },
  });

  React.useEffect(() => {
    if (!inputRef.current) return;
    inputRef.current.style.height = "auto";
    inputRef.current.style.height = `${Math.min(inputRef.current.scrollHeight, 180)}px`;
  }, [value]);

  React.useEffect(() => {
    const handler = (event: Event) => {
      const custom = event as CustomEvent<IronManSettings>;
      if (custom.detail) setIronManSettings(custom.detail);
    };
    window.addEventListener(IRONMAN_SETTINGS_EVENT, handler as EventListener);
    return () => {
      window.removeEventListener(IRONMAN_SETTINGS_EVENT, handler as EventListener);
    };
  }, []);

  const handleFinalVoiceText = (text: string) => {
    if (!text.trim()) return;
    const next = value.trim() ? `${value.trim()} ${text.trim()}` : text.trim();
    onChange(next);
  };

  return (
    <div className="space-y-3">
      {attachments.length ? (
        <div className="flex flex-wrap gap-2">
          {attachments.map((file) => (
            <div
              key={file.id}
              className="flex items-center gap-2 rounded-lg border border-border bg-muted px-3 py-1 text-xs text-muted-foreground"
            >
              {file.previewUrl ? (
                <Image
                  src={file.previewUrl}
                  alt={file.name}
                  width={32}
                  height={32}
                  className="h-8 w-8 rounded-md object-cover"
                  unoptimized
                />
              ) : null}
              <span>{file.name}</span>
              <span>{Math.round(file.size / 1024)}kb</span>
              <button
                type="button"
                className="text-muted-foreground/60 hover:text-foreground"
                onClick={() => onRemoveFile(file.id)}
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      ) : null}
      <div
        {...getRootProps()}
        className={`flex items-end gap-3 rounded-2xl border bg-card p-4 shadow-sm transition focus-within:ring-2 focus-within:ring-ring/50 ${
          isDragActive ? "border-emerald-400 bg-emerald-500/10" : "border-border"
        }`}
      >
        <input {...getInputProps()} />
        <button
          type="button"
          disabled={isStreaming}
          onClick={openFilePicker}
          className="inline-flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full border border-border bg-muted text-muted-foreground transition hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed md:h-10 md:w-10"
          title="Attach file"
        >
          <Paperclip className="h-4 w-4" />
        </button>
        {ironManSettings.voiceEnabled ? (
          <VoiceInput
            language={ironManSettings.sttLanguage}
            disabled={isStreaming}
            onInterimText={setInterimTranscript}
            onFinalText={handleFinalVoiceText}
          />
        ) : null}
        <Textarea
          ref={inputRef}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Type a command or ask a question..."
          className="min-h-[48px] flex-1 resize-none border-0 bg-transparent p-0 text-sm text-foreground placeholder:text-muted-foreground/50 focus-visible:ring-0"
          disabled={isStreaming}
          onKeyDown={(event) => {
            if (event.key !== "Enter") return;
            if (event.shiftKey) return;
            if (event.ctrlKey || event.metaKey || !event.shiftKey) {
              event.preventDefault();
              onSend();
            }
          }}
        />
        <Button
          type="button"
          size="icon"
          onClick={isStreaming ? onStop : onSend}
          className="h-11 w-11 rounded-full md:h-10 md:w-10"
          disabled={!isStreaming && !value.trim() && !attachments.length}
        >
          {isStreaming ? <Square className="h-4 w-4" /> : <Send className="h-4 w-4" />}
        </Button>
      </div>
      {interimTranscript ? (
        <div className="px-2 text-xs italic text-muted-foreground/80">{interimTranscript}</div>
      ) : null}
    </div>
  );
}
