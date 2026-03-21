import NextAuth, { type User } from "next-auth";
import Credentials from "next-auth/providers/credentials";

interface LoginResponse {
  access_token: string;
  user?: {
    id?: string;
    name?: string;
    email?: string;
  };
}
interface ExtendedUser extends User {
  accessToken: string;
  remember?: boolean;
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
        remember: { label: "Remember me", type: "text" },
      },
      async authorize(credentials): Promise<User | null> {
        if (!credentials?.email || !credentials?.password) return null;

        // Bỏ qua check backend nếu dùng tài khoản admin mặc định
        if (credentials.email === "admin@ironcore.ai" && credentials.password === "admin") {
          return {
            id: "admin-1",
            name: "Super Admin",
            email: "admin@ironcore.ai",
            accessToken: "dev-key",
            remember: credentials.remember === "true",
          } as ExtendedUser;
        }

        const backendUrl = process.env.NEXT_PUBLIC_API_URL?.trim();
        if (backendUrl) {
          try {
            const res = await fetch(
              `${backendUrl}/auth/login`,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  email: String(credentials.email),
                  password: String(credentials.password),
                  remember: credentials.remember === "true",
                }),
              }
            );

            if (res.ok) {
              const data = (await res.json()) as LoginResponse;
              if (data.access_token) {
                const user: ExtendedUser = {
                  id: String(data.user?.id ?? credentials.email ?? ""),
                  name: String(data.user?.name ?? credentials.email ?? ""),
                  email: String(data.user?.email ?? credentials.email ?? ""),
                  accessToken: data.access_token,
                  remember: credentials.remember === "true",
                };
                return user;
              }
            }
          } catch {
            // fall through to local dev auth
          }
        }

        const { authenticateDevUser } = await import("@/lib/server/dev-auth-store");
        const localUser = await authenticateDevUser(
          String(credentials.email),
          String(credentials.password)
        );
        if (!localUser) return null;

        return {
          ...localUser,
          accessToken: `local-dev:${localUser.id}`,
          remember: credentials.remember === "true",
        } as ExtendedUser;
      },
    }),
  ],
  callbacks: {
    jwt({ token, user, trigger, session }) {
      if (user) {
        const nextUser = user as ExtendedUser;
        token.accessToken = nextUser.accessToken;
        const now = Math.floor(Date.now() / 1000);
        const longLived = 60 * 60 * 24 * 30;
        const shortLived = 60 * 60 * 8;
        token.exp = now + (nextUser.remember ? longLived : shortLived);
      }
      if (trigger === "update" && session?.apiKey) {
        token.apiKey = session.apiKey;
      }
      return token;
    },
    session({ session, token }) {
      session.accessToken = token.accessToken as string | undefined;
      session.apiKey = token.apiKey as string | undefined;
      return session;
    },
  },
  pages: {
    signIn: "/chat",
    error: "/chat",
  },
  session: {
    strategy: "jwt",
    maxAge: 60 * 60 * 24 * 30,
  },
});
