"use client";

import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { ControlPlaneNav } from "@/components/control-plane/ControlPlaneNav";

interface SchedulerJob {
  id: string;
  name: string;
  cron: string;
  next_run_at: number | null;
  status: "running" | "idle" | "error" | "paused";
  last_error?: string | null;
}

const statusClass: Record<SchedulerJob["status"], string> = {
  running: "bg-blue-500/15 text-blue-500",
  idle: "bg-muted text-muted-foreground",
  error: "bg-red-500/15 text-red-500",
  paused: "bg-yellow-500/15 text-yellow-600",
};

export default function DashboardCronPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = React.useState(false);
  const [name, setName] = React.useState("");
  const [cron, setCron] = React.useState("*/5 * * * *");

  const jobsQuery = useQuery({
    queryKey: ["scheduler-jobs"],
    queryFn: async () => {
      const res = await fetch("/api/scheduler/jobs", { cache: "no-store" });
      if (!res.ok) throw new Error("scheduler unavailable");
      const rows = (await res.json()) as Array<{
        job_id: string;
        name: string;
        schedule: string;
        next_run_time?: number | null;
        status: string;
        last_error?: string | null;
      }>;
      return rows.map((r) => ({
        id: r.job_id,
        name: r.name,
        cron: r.schedule,
        next_run_at: r.next_run_time ?? null,
        status: (r.status === "running" || r.status === "paused" || r.status === "error" ? r.status : "idle") as SchedulerJob["status"],
        last_error: r.last_error,
      }));
    },
    refetchInterval: 15_000,
    retry: 0,
  });

  const jobs = jobsQuery.data ?? [];

  const runAction = async (jobId: string, action: "pause" | "resume" | "trigger" | "delete") => {
    if (action === "delete" && !window.confirm("Delete this job?")) return;
    try {
      let res: Response;
      if (action === "delete") {
        res = await fetch(`/api/scheduler/jobs/${jobId}`, { method: "DELETE" });
      } else {
        res = await fetch(`/api/scheduler/jobs/${jobId}/${action}`, { method: "POST" });
      }
      if (!res.ok) {
        throw new Error("Scheduler backend unavailable");
      }
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Scheduler action failed");
    } finally {
      queryClient.invalidateQueries({ queryKey: ["scheduler-jobs"] });
    }
  };

  const createJob = async () => {
    if (!name.trim()) return;
    const cronParts = cron.trim().split(/\s+/);
    if (cronParts.length < 5 || cronParts.length > 6) {
      window.alert("Cron expression must have 5-6 fields");
      return;
    }
    try {
      const res = await fetch("/api/scheduler/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), cron_expression: cron.trim(), task_type: "built_in", task_config: { action: "health_check" } }),
      });
      if (!res.ok) {
        throw new Error("Scheduler backend unavailable");
      }
      setName("");
      setCron("*/5 * * * *");
      setShowCreate(false);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Create job failed");
    } finally {
      queryClient.invalidateQueries({ queryKey: ["scheduler-jobs"] });
    }
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Scheduler Console</h1>
        <p className="text-sm text-muted-foreground">Quản lý cron jobs: pause/resume/run-now/delete và tạo lịch mới.</p>
      </div>

      <ControlPlaneNav />

      <Card className="border border-border bg-card p-5">
        <div className="mb-3 flex items-center justify-between">
          <div className="text-sm font-semibold">Jobs</div>
          <Button size="sm" onClick={() => setShowCreate((v) => !v)}>{showCreate ? "Close" : "Create job"}</Button>
        </div>

        {showCreate && (
          <div className="mb-4 grid gap-3 rounded-lg border border-border p-3 md:grid-cols-3">
            <div className="space-y-1">
              <Label>Job name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="daily-report" />
            </div>
            <div className="space-y-1 md:col-span-2">
              <Label>Cron expression</Label>
              <Input value={cron} onChange={(e) => setCron(e.target.value)} placeholder="*/5 * * * *" />
            </div>
            <div className="md:col-span-3">
              <Button size="sm" onClick={createJob}>Save</Button>
            </div>
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="pb-2">Name</th>
                <th className="pb-2">Schedule</th>
                <th className="pb-2">Next run</th>
                <th className="pb-2">Status</th>
                <th className="pb-2">Last error</th>
                <th className="pb-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id} className="border-t border-border/70">
                  <td className="py-2">{job.name}</td>
                  <td className="py-2 font-mono text-xs">{job.cron}</td>
                  <td className="py-2 text-xs">{job.next_run_at ? new Date(job.next_run_at * 1000).toLocaleString() : "-"}</td>
                  <td className="py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs ${statusClass[job.status]}`}>{job.status}</span>
                  </td>
                  <td className="py-2 text-xs text-muted-foreground">{job.last_error || "-"}</td>
                  <td className="py-2">
                    <div className="flex flex-wrap gap-2">
                      <button type="button" className="rounded bg-muted px-2 py-1 text-xs" onClick={() => runAction(job.id, "pause")}>Pause</button>
                      <button type="button" className="rounded bg-muted px-2 py-1 text-xs" onClick={() => runAction(job.id, "resume")}>Resume</button>
                      <button type="button" className="rounded bg-muted px-2 py-1 text-xs" onClick={() => runAction(job.id, "trigger")}>Run now</button>
                      <button type="button" className="rounded bg-red-500/15 px-2 py-1 text-xs text-red-500" onClick={() => runAction(job.id, "delete")}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {jobs.length === 0 ? (
                <tr>
                  <td className="py-6 text-sm text-muted-foreground" colSpan={6}>
                    No scheduler jobs are available from the backend yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
