/**
 * Auth.js v5 config with an HS256 JWT override.
 *
 * The FastAPI backend (see backend/app/auth.py) expects every dashboard
 * request to carry `Authorization: Bearer <jwt>` where the JWT is an HS256
 * token signed with the shared AUTH_SECRET. Auth.js v5 defaults to a JWE,
 * so we override jwt.encode/decode to emit and accept a plain HS256 JWT.
 *
 * Note: we don't need to re-sign on every backend request — Auth.js stores
 * the HS256 JWT verbatim in the session cookie, so the /api/backend proxy
 * can lift it straight out of the cookie.
 */
import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import { SignJWT, jwtVerify, type JWTPayload } from "jose";

const secret = new TextEncoder().encode(process.env.AUTH_SECRET!);

/**
 * Hardcoded test users. This is an internal platform — no external IdP needed.
 * Add / remove rows here to manage dashboard access. Passwords are stored in
 * plaintext on purpose: this is a dev / single-tenant platform, not a
 * consumer product. Rotate by editing this file and redeploying.
 */
const TEST_USERS: Record<string, { password: string; name: string }> = {
  "admin@curator.local": { password: "curator", name: "Admin" },
  "shivam@curator.local": { password: "curator", name: "Shivam" },
};

export const SESSION_COOKIE_NAMES = [
  // Dev (http) cookie.
  "authjs.session-token",
  // Prod (https) cookie — Auth.js prefixes with __Secure- in prod.
  "__Secure-authjs.session-token",
];

export const { auth, handlers, signIn, signOut } = NextAuth({
  providers: [
    Credentials({
      name: "Email + Password",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(creds) {
        const email = String(creds?.email ?? "").trim().toLowerCase();
        const password = String(creds?.password ?? "");
        const user = TEST_USERS[email];
        if (!user || user.password !== password) return null;
        return { id: email, email, name: user.name };
      },
    }),
  ],
  session: { strategy: "jwt" },
  pages: {
    signIn: "/signin",
  },
  callbacks: {
    async jwt({ token, user }) {
      // On initial sign-in, copy email from the authorize() return value.
      // Subsequent requests already have it on the token.
      if (user?.email && !token.email) token.email = user.email;
      return token;
    },
    async session({ session, token }) {
      if (token.email) session.user = { ...session.user, email: token.email as string };
      return session;
    },
  },
  jwt: {
    encode: async ({ token, maxAge }) => {
      if (!token) throw new Error("missing token to encode");
      const exp = Math.floor(Date.now() / 1000) + (maxAge ?? 60 * 60 * 24 * 30);
      return await new SignJWT(token as JWTPayload)
        .setProtectedHeader({ alg: "HS256" })
        .setIssuedAt()
        .setExpirationTime(exp)
        .sign(secret);
    },
    decode: async ({ token }) => {
      if (!token) return null;
      try {
        const { payload } = await jwtVerify(token, secret, { algorithms: ["HS256"] });
        return payload as JWTPayload;
      } catch {
        return null;
      }
    },
  },
});
