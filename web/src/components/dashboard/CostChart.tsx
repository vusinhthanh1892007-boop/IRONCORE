"use client";

import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";

interface ChartPoint {
  timestamp: number;
  value: number;
  label?: string;
}

interface CostChartProps {
  data: ChartPoint[];
  savingsPct?: number;
}

const formatLabel = (point: ChartPoint) => {
  if (point.label) return point.label;
  const date = new Date(point.timestamp * 1000);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

export function CostChart({ data, savingsPct = 0 }: CostChartProps) {
  const scale = savingsPct > 0 && savingsPct < 100 ? 1 / (1 - savingsPct / 100) : 1;
  const chartData = data.map((point) => ({
    label: formatLabel(point),
    withOptimizer: point.value,
    withoutOptimizer: Number((point.value * scale).toFixed(6)),
  }));

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
        <LineChart data={chartData} margin={{ left: 8, right: 8, top: 10, bottom: 10 }}>
          <CartesianGrid stroke="rgba(63,63,70,0.3)" strokeDasharray="3 3" />
          <XAxis dataKey="label" tick={{ fill: "#71717a", fontSize: 11 }} />
          <YAxis tick={{ fill: "#71717a", fontSize: 11 }} />
          <Tooltip
            contentStyle={{
              background: "#0a0a0a",
              border: "1px solid #27272a",
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          <Line
            type="monotone"
            dataKey="withOptimizer"
            stroke="#22c55e"
            strokeWidth={2}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="withoutOptimizer"
            stroke="#ef4444"
            strokeDasharray="6 4"
            strokeWidth={1.5}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
