"use client";

import * as React from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type SectionProvider = {
  provider_id: string;
  provider_name: string;
  preview: string;
  short_description: string;
  models_endpoint: string;
};

type CatalogSection = {
  id: string;
  title: string;
  description: string;
  providers: SectionProvider[];
};

type ModelsResponse = {
  action: string;
  provider: string;
  provider_id: string;
  models: Array<{
    model_id: string;
    model_name: string;
    short_description: string;
    context_window?: number;
    tags: string[];
    example_endpoint_if_known?: string;
  }>;
  pagination: {
    page: number;
    page_size: number;
    total_items: number;
    total_pages: number;
    has_next: boolean;
    has_prev: boolean;
  };
  filter: string;
  notice?: string;
  last_updated: string;
};

export default function AiCatalogPage() {
  const [sections, setSections] = React.useState<CatalogSection[]>([]);
  const [loadingSections, setLoadingSections] = React.useState(true);
  const [latestMode, setLatestMode] = React.useState(false);
  const [selectedProvider, setSelectedProvider] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [modelsData, setModelsData] = React.useState<ModelsResponse | null>(null);
  const [loadingModels, setLoadingModels] = React.useState(false);
  const [markdown, setMarkdown] = React.useState("");
  const [loadingMarkdown, setLoadingMarkdown] = React.useState(false);
  const [addModelProvider, setAddModelProvider] = React.useState("");
  const [addModelId, setAddModelId] = React.useState("");
  const [addModelName, setAddModelName] = React.useState("");
  const [addMessage, setAddMessage] = React.useState("");

  const providerOptions = React.useMemo(() => {
    const map = new Map<string, string>();
    sections.forEach((section) => {
      section.providers.forEach((provider) => {
        map.set(provider.provider_id, provider.provider_name);
      });
    });
    return Array.from(map.entries())
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [sections]);

  const loadSections = React.useCallback(async () => {
    setLoadingSections(true);
    const res = await fetch(`/api/ai-catalog/sections?latest=${latestMode ? "true" : "false"}`, {
      cache: "no-store",
    });
    const payload = (await res.json()) as { sections: CatalogSection[] };
    setSections(payload.sections ?? []);
    setLoadingSections(false);
  }, [latestMode]);

  const loadMarkdown = React.useCallback(async () => {
    setLoadingMarkdown(true);
    const res = await fetch(`/api/ai-catalog/markdown?latest=${latestMode ? "true" : "false"}`, {
      cache: "no-store",
    });
    const payload = (await res.json()) as { markdown?: string };
    setMarkdown(payload.markdown ?? "");
    setLoadingMarkdown(false);
  }, [latestMode]);

  const loadModels = React.useCallback(
    async (provider: string, targetPage: number, targetFilter: string) => {
      if (!provider) return;
      setLoadingModels(true);
      const res = await fetch(
        `/api/ai-catalog/models?provider=${encodeURIComponent(provider)}&page=${targetPage}&filter=${encodeURIComponent(
          targetFilter
        )}&latest=${latestMode ? "true" : "false"}`,
        { cache: "no-store" }
      );
      const payload = (await res.json()) as ModelsResponse;
      setModelsData(payload);
      setLoadingModels(false);
    },
    [latestMode]
  );

  React.useEffect(() => {
    void loadSections();
    void loadMarkdown();
  }, [loadSections, loadMarkdown]);

  React.useEffect(() => {
    if (!selectedProvider) return;
    void loadModels(selectedProvider, page, query);
  }, [selectedProvider, page, query, loadModels]);

  const handleSelectProvider = (providerId: string) => {
    setSelectedProvider(providerId);
    setPage(1);
  };

  const handleAddModel = async () => {
    setAddMessage("");
    const res = await fetch("/api/ai-catalog/models/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: addModelProvider,
        model_id: addModelId,
        model_name: addModelName || undefined,
      }),
    });
    const payload = (await res.json()) as { message?: string; note?: string };
    setAddMessage([payload.message, payload.note].filter(Boolean).join(" · "));

    if (res.ok && selectedProvider && selectedProvider === addModelProvider) {
      void loadModels(selectedProvider, 1, query);
      setPage(1);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">AI Content & UI Generator</h1>
        <p className="text-sm text-muted-foreground">
          Top-level sections only, chi tiết model hiển thị khi chọn provider. last_updated: 2026-03-12
        </p>
      </div>

      <Card className="border border-border bg-card p-4">
        <div className="flex flex-wrap items-center gap-3">
          <label className="inline-flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={latestMode}
              onChange={(event) => setLatestMode(event.target.checked)}
            />
            Cập nhật mới nhất
          </label>
          <Button variant="outline" onClick={() => { void loadSections(); void loadMarkdown(); if (selectedProvider) void loadModels(selectedProvider, page, query); }}>
            Refresh
          </Button>
          {latestMode ? (
            <span className="text-xs text-muted-foreground">Tùy chọn cập nhật web khả dụng</span>
          ) : null}
        </div>
      </Card>

      <Card className="border border-border bg-card p-4">
        <div className="mb-3 text-sm font-semibold">TOC</div>
        <ul className="space-y-1 text-sm">
          {sections.map((section) => (
            <li key={section.id}>• {section.title}</li>
          ))}
        </ul>
      </Card>

      <div className="space-y-4">
        {loadingSections ? (
          <Card className="border border-border bg-card p-4 text-sm text-muted-foreground">Loading sections...</Card>
        ) : null}

        {sections.map((section) => (
          <Card key={section.id} className="border border-border bg-card p-4">
            <h2 className="text-lg font-semibold">{section.title}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{section.description}</p>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {section.providers.map((provider) => (
                <div key={provider.provider_id} className="rounded-lg border border-border p-3">
                  <div className="text-sm font-semibold">Provider: {provider.provider_name}</div>
                  <div className="text-xs text-muted-foreground">{provider.short_description}</div>
                  <div className="mt-2 text-xs text-muted-foreground">Preview: {provider.preview}</div>
                  <Button
                    size="sm"
                    className="mt-3"
                    onClick={() => handleSelectProvider(provider.provider_id)}
                  >
                    👉 Xem models của {provider.provider_name}
                  </Button>
                </div>
              ))}
            </div>
          </Card>
        ))}
      </div>

      <Card className="border border-border bg-card p-4 space-y-4">
        <div className="text-sm font-semibold">Tương tác chọn provider → hiện model</div>
        <div className="grid gap-3 md:grid-cols-3">
          <div className="space-y-1">
            <Label>Provider</Label>
            <select
              value={selectedProvider}
              onChange={(event) => {
                setSelectedProvider(event.target.value);
                setPage(1);
              }}
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">Chọn provider...</option>
              {providerOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.name}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label>filter(query)</Label>
            <Input
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setPage(1);
              }}
              placeholder="tìm theo tên, ctx, tags"
            />
          </div>
          <div className="space-y-1">
            <Label>Page</Label>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((prev) => Math.max(1, prev - 1))}>Prev</Button>
              <span className="text-sm">{modelsData?.pagination.page ?? page}</span>
              <Button
                variant="outline"
                size="sm"
                disabled={!!modelsData && !modelsData.pagination.has_next}
                onClick={() => setPage((prev) => prev + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        </div>

        {loadingModels ? (
          <div className="text-sm text-muted-foreground">Loading models...</div>
        ) : null}

        {modelsData ? (
          <div className="space-y-3">
            <div className="text-xs text-muted-foreground">
              provider={modelsData.provider} · page_size={modelsData.pagination.page_size} · total={modelsData.pagination.total_items} · last_updated={modelsData.last_updated}
            </div>
            {modelsData.notice ? <div className="text-xs text-muted-foreground">{modelsData.notice}</div> : null}
            <div className="grid gap-2 md:grid-cols-2">
              {modelsData.models.map((model) => (
                <div key={model.model_id} className="rounded-lg border border-border p-3">
                  <div className="text-sm font-semibold">{model.model_name}</div>
                  <div className="text-xs text-muted-foreground">{model.model_id}</div>
                  <div className="mt-1 text-xs">{model.short_description}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    ctx: {model.context_window ?? "n/a"} · tags: {model.tags.join(", ")}
                  </div>
                </div>
              ))}
            </div>
            <pre className="overflow-auto rounded-md border border-border bg-muted p-3 text-xs">
{JSON.stringify(modelsData, null, 2)}
            </pre>
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">Chưa chọn provider.</div>
        )}
      </Card>

      <Card className="border border-border bg-card p-4 space-y-3">
        <div className="text-sm font-semibold">Thêm model vào danh sách</div>
        <div className="grid gap-3 md:grid-cols-3">
          <div className="space-y-1">
            <Label>Provider</Label>
            <select
              value={addModelProvider}
              onChange={(event) => setAddModelProvider(event.target.value)}
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">Chọn provider...</option>
              {providerOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.name}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label>model_id (provider/model_name)</Label>
            <Input value={addModelId} onChange={(event) => setAddModelId(event.target.value)} placeholder="meta/llama4-new" />
          </div>
          <div className="space-y-1">
            <Label>model_name (optional)</Label>
            <Input value={addModelName} onChange={(event) => setAddModelName(event.target.value)} placeholder="Llama 4 New" />
          </div>
        </div>
        <Button onClick={handleAddModel}>Thêm model</Button>
        {addMessage ? <div className="text-xs text-muted-foreground">{addMessage}</div> : null}
      </Card>

      <Card className="border border-border bg-card p-4">
        <div className="mb-2 text-sm font-semibold">Markdown output</div>
        {loadingMarkdown ? <div className="text-sm text-muted-foreground">Loading markdown...</div> : null}
        <pre className="max-h-[420px] overflow-auto rounded-md border border-border bg-muted p-3 text-xs">{markdown}</pre>
      </Card>
    </div>
  );
}
