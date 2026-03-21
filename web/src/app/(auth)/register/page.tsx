"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { Controller } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";

const schema = z
  .object({
    name: z.string().min(2, "Name is required"),
    email: z.string().email("Invalid email"),
    password: z.string().min(8, "At least 8 characters"),
    confirmPassword: z.string().min(8),
    accepted: z.boolean().refine((val) => val, "Accept terms"),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

type FormValues = z.infer<typeof schema>;

const strengthLabel = (password: string) => {
  if (password.length >= 12) return { label: "Strong", value: 100 };
  if (password.length >= 9) return { label: "Fair", value: 66 };
  if (password.length >= 8) return { label: "Weak", value: 33 };
  return { label: "", value: 0 };
};

export default function RegisterPage() {
  const router = useRouter();
  const {
    register,
    handleSubmit,
    control,
    watch,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { accepted: false },
  });

  const passwordValue = watch("password") ?? "";
  const strength = strengthLabel(passwordValue);

  const onSubmit = async (values: FormValues) => {
    const res = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: values.name,
        email: values.email,
        password: values.password,
      }),
    });

    if (!res.ok) {
      const payload = (await res.json().catch(() => ({ message: "Registration failed." }))) as {
        message?: string;
      };
      setError("email", { message: payload.message ?? "Registration failed." });
      return;
    }

    router.push("/chat?registered=1");
  };

  return (
    <div className="w-full rounded-2xl border border-zinc-200 bg-white p-8 shadow-sm">
      <h1 className="text-2xl font-semibold">Create account</h1>
      <p className="mt-1 text-sm text-zinc-500">
        Set up your IronCore operator profile.
      </p>

      <form onSubmit={handleSubmit(onSubmit)} className="mt-6 space-y-4">
        <div className="space-y-1">
          <label className="text-xs font-medium text-zinc-600">Name</label>
          <Input {...register("name")} placeholder="User Name" />
          {errors.name ? (
            <p className="text-xs text-red-600">{errors.name.message}</p>
          ) : null}
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-zinc-600">Email</label>
          <Input type="email" {...register("email")} placeholder="you@company.com" />
          {errors.email ? (
            <p className="text-xs text-red-600">{errors.email.message}</p>
          ) : null}
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-zinc-600">Password</label>
          <Input type="password" {...register("password")} />
          <div className="mt-2 h-1 w-full rounded-full bg-zinc-100">
            <div
              className="h-1 rounded-full bg-zinc-900"
              style={{ width: `${strength.value}%` }}
            />
          </div>
          {strength.label ? (
            <p className="text-xs text-zinc-500">{strength.label}</p>
          ) : null}
          {errors.password ? (
            <p className="text-xs text-red-600">{errors.password.message}</p>
          ) : null}
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-zinc-600">Confirm</label>
          <Input type="password" {...register("confirmPassword")} />
          {errors.confirmPassword ? (
            <p className="text-xs text-red-600">{errors.confirmPassword.message}</p>
          ) : null}
        </div>
        <label className="flex items-center gap-2 text-xs text-zinc-600">
          <Controller
            control={control}
            name="accepted"
            render={({ field }) => (
              <Checkbox
                checked={field.value}
                onCheckedChange={(checked) => field.onChange(Boolean(checked))}
              />
            )}
          />
          I agree to the terms
        </label>
        {errors.accepted ? (
          <p className="text-xs text-red-600">{errors.accepted.message}</p>
        ) : null}

        <Button type="submit" className="w-full" disabled={isSubmitting}>
          Create account
        </Button>
      </form>

      <div className="mt-4 text-xs text-zinc-500">
        Continue to <Link href="/chat">Chat</Link>
      </div>
    </div>
  );
}
