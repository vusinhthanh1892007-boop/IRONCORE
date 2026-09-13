"use client";

import * as React from "react";
import { Globe } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/components/providers/I18nProvider";

export function LanguageSelector() {
  const { language, setLanguage, options } = useI18n();
  const [query, setQuery] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const [selected, setSelected] = React.useState(language);

  React.useEffect(() => {
    setSelected(language);
  }, [language]);

  const filtered = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((item) => item.label.toLowerCase().includes(needle) || item.code.toLowerCase().includes(needle));
  }, [options, query]);

  const currentLabel = options.find((item) => item.code === language)?.label ?? `Language (${language})`;

  return (
    <div className="rounded-lg border border-border bg-muted/30 p-2">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left text-xs text-muted-foreground hover:bg-muted"
      >
        <span className="inline-flex items-center gap-1">
          <Globe className="h-3.5 w-3.5" />
          Interface language
        </span>
        <span className="max-w-[120px] truncate text-[11px]">{currentLabel}</span>
      </button>

      {open ? (
        <div className="mt-2 space-y-2">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search language"
            className="h-8"
          />
          <select
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            className="h-36 w-full rounded-md border border-input bg-background px-2 py-1 text-xs"
            size={7}
          >
            {filtered.map((item) => (
              <option key={item.code} value={item.code}>
                {item.label}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            className="w-full"
            onClick={() => {
              setLanguage(selected);
            }}
          >
            Apply language
          </Button>
        </div>
      ) : null}
    </div>
  );
}
