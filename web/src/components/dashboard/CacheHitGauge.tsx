"use client";

import { RadialBar, RadialBarChart, ResponsiveContainer } from "recharts";

interface CacheHitGaugeProps {
  value: number;
}

const colorForValue = (value: number) => {
  if (value < 40) return "#ef4444";
  if (value < 70) return "#f59e0b";
  return "#22c55e";
};

export function CacheHitGauge({ value }: CacheHitGaugeProps) {
  const data = [{ name: "cache", value }];
  const color = colorForValue(value);

  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
        <RadialBarChart
          innerRadius="70%"
          outerRadius="100%"
          data={data}
          startAngle={180}
          endAngle={0}
        >
          <RadialBar dataKey="value" fill={color} cornerRadius={10} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="-mt-32 flex flex-col items-center text-center">
        <div className="text-3xl font-semibold text-zinc-100">
          {value.toFixed(1)}%
        </div>
        <div className="text-xs text-zinc-500">Cache Hit Rate</div>
      </div>
    </div>
  );
}
