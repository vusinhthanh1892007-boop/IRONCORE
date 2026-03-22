import "next-auth";

declare module "next-auth" {
  interface Session {
    accessToken?: string;
    apiKey?: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    apiKey?: string;
  }
}
