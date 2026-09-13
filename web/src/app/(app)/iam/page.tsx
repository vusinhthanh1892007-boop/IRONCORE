"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface IamUser {
  username: string;
  email: string;
  roles: string[];
  last_login: string;
  status: "active" | "disabled";
}

interface IamRole {
  role_name: string;
  permissions: string[];
  users_count: number;
}

interface SsoMapping {
  id: string;
  provider: string;
  group: string;
  role: string;
}

interface VaultBinding {
  secret_name: string;
  service: string;
  status: "active" | "expired";
}

export default function IamPage() {
  const usersQuery = useQuery({
    queryKey: ["iam-users"],
    queryFn: async () => {
      const res = await fetch("/api/enterprise/iam/users", { cache: "no-store" });
      if (!res.ok) throw new Error("IAM users unavailable");
      return (await res.json()) as IamUser[];
    },
    refetchInterval: 15000,
    retry: 0,
  });

  const rolesQuery = useQuery({
    queryKey: ["iam-roles"],
    queryFn: async () => {
      const res = await fetch("/api/enterprise/iam/roles", { cache: "no-store" });
      if (!res.ok) throw new Error("IAM roles unavailable");
      return (await res.json()) as IamRole[];
    },
    refetchInterval: 15000,
    retry: 0,
  });

  const mappingsQuery = useQuery({
    queryKey: ["iam-sso-mappings"],
    queryFn: async () => {
      const res = await fetch("/api/enterprise/iam/sso-mappings", { cache: "no-store" });
      if (!res.ok) throw new Error("IAM mappings unavailable");
      return (await res.json()) as SsoMapping[];
    },
    refetchInterval: 15000,
    retry: 0,
  });

  const vaultQuery = useQuery({
    queryKey: ["iam-vault-bindings"],
    queryFn: async () => {
      const res = await fetch("/api/enterprise/iam/vault-bindings", { cache: "no-store" });
      if (!res.ok) throw new Error("IAM vault bindings unavailable");
      return (await res.json()) as VaultBinding[];
    },
    refetchInterval: 15000,
    retry: 0,
  });

  const [mappings, setMappings] = React.useState<SsoMapping[]>([]);
  const [newProvider, setNewProvider] = React.useState("azure_entra");
  const [newGroup, setNewGroup] = React.useState("");
  const [newRole, setNewRole] = React.useState("operator");

  React.useEffect(() => {
    if (mappingsQuery.data) setMappings(mappingsQuery.data);
  }, [mappingsQuery.data]);

  const addMapping = () => {
    if (!newGroup.trim()) return;
    setMappings((prev) => [
      {
        id: `local-${Date.now()}`,
        provider: newProvider,
        group: newGroup.trim(),
        role: newRole,
      },
      ...prev,
    ]);
    setNewGroup("");
  };

  const removeMapping = (id: string) => {
    setMappings((prev) => prev.filter((row) => row.id !== id));
  };

  const users = usersQuery.data ?? [];
  const roles = rolesQuery.data ?? [];
  const vault = vaultQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">IAM Dashboard</h1>
        <p className="text-sm text-muted-foreground">Manage users, roles, SSO mappings, and vault bindings.</p>
      </div>

      <Card className="border border-border bg-card p-5">
        <Tabs defaultValue="users">
          <TabsList>
            <TabsTrigger value="users">Users</TabsTrigger>
            <TabsTrigger value="roles">Roles</TabsTrigger>
            <TabsTrigger value="sso">SSO Mappings</TabsTrigger>
            <TabsTrigger value="vault">Vault Bindings</TabsTrigger>
          </TabsList>

          <TabsContent value="users" className="mt-4 space-y-3">
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline">Add user</Button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="pb-2">Username</th>
                    <th className="pb-2">Email</th>
                    <th className="pb-2">Roles</th>
                    <th className="pb-2">Last login</th>
                    <th className="pb-2">Status</th>
                    <th className="pb-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.username} className="border-t border-border/70">
                      <td className="py-2">{user.username}</td>
                      <td className="py-2">{user.email}</td>
                      <td className="py-2">{user.roles.join(", ")}</td>
                      <td className="py-2 text-xs">{new Date(user.last_login).toLocaleString()}</td>
                      <td className="py-2">
                        <span className={user.status === "active" ? "rounded bg-emerald-500/15 px-2 py-1 text-xs text-emerald-500" : "rounded bg-zinc-500/15 px-2 py-1 text-xs text-zinc-500"}>
                          {user.status}
                        </span>
                      </td>
                      <td className="py-2">
                        <div className="flex flex-wrap gap-2">
                          <button type="button" className="rounded bg-muted px-2 py-1 text-xs">Edit roles</button>
                          <button type="button" className="rounded bg-red-500/15 px-2 py-1 text-xs text-red-500">Disable</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </TabsContent>

          <TabsContent value="roles" className="mt-4 space-y-3">
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="outline">Create role</Button>
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {roles.map((role) => (
                <div key={role.role_name} className="rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between">
                    <div className="font-medium">{role.role_name}</div>
                    <button type="button" className="rounded bg-muted px-2 py-1 text-xs">Edit</button>
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground">Users: {role.users_count}</div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {role.permissions.map((perm) => (
                      <span key={perm} className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">{perm}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="sso" className="mt-4 space-y-4">
            <div className="grid gap-2 md:grid-cols-4">
              <select value={newProvider} onChange={(e) => setNewProvider(e.target.value)} className="h-10 rounded-md border border-input bg-background px-3 text-sm">
                <option value="azure_entra">Azure AD / Entra</option>
                <option value="okta">Okta</option>
                <option value="adfs">ADFS</option>
                <option value="oidc">Generic OIDC</option>
              </select>
              <Input value={newGroup} onChange={(e) => setNewGroup(e.target.value)} placeholder="Group name" />
              <Input value={newRole} onChange={(e) => setNewRole(e.target.value)} placeholder="IronCore role" />
              <Button onClick={addMapping}>Add mapping</Button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="pb-2">Provider</th>
                    <th className="pb-2">Group</th>
                    <th className="pb-2">Role</th>
                    <th className="pb-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {mappings.map((row) => (
                    <tr key={row.id} className="border-t border-border/70">
                      <td className="py-2">{row.provider}</td>
                      <td className="py-2">{row.group}</td>
                      <td className="py-2">{row.role}</td>
                      <td className="py-2">
                        <button type="button" className="rounded bg-red-500/15 px-2 py-1 text-xs text-red-500" onClick={() => removeMapping(row.id)}>
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </TabsContent>

          <TabsContent value="vault" className="mt-4 space-y-2">
            {vault.map((row) => (
              <div key={`${row.secret_name}-${row.service}`} className="rounded-lg border border-border p-3 text-sm">
                <div className="font-mono text-xs">{row.secret_name}</div>
                <div className="mt-1 text-xs text-muted-foreground">service: {row.service}</div>
                <div className="mt-1">
                  <span className={row.status === "active" ? "rounded bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-500" : "rounded bg-yellow-500/15 px-2 py-0.5 text-xs text-yellow-600"}>
                    {row.status}
                  </span>
                </div>
              </div>
            ))}
          </TabsContent>
        </Tabs>
      </Card>
    </div>
  );
}
