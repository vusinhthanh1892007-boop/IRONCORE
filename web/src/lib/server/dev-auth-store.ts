import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

interface StoredUser {
  id: string;
  name: string;
  email: string;
  passwordHash: string;
  salt: string;
  createdAt: string;
}

const DATA_DIR = path.join(process.cwd(), ".data");
const USERS_PATH = path.join(DATA_DIR, "users.json");

async function readUsers(): Promise<StoredUser[]> {
  try {
    const raw = await readFile(USERS_PATH, "utf-8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as StoredUser[]) : [];
  } catch {
    return [];
  }
}

async function writeUsers(users: StoredUser[]) {
  await mkdir(DATA_DIR, { recursive: true });
  await writeFile(USERS_PATH, JSON.stringify(users, null, 2), "utf-8");
}

function hashPassword(password: string, salt: string) {
  return scryptSync(password, salt, 64).toString("hex");
}

function verifyPassword(password: string, salt: string, passwordHash: string) {
  const actual = Buffer.from(hashPassword(password, salt), "hex");
  const expected = Buffer.from(passwordHash, "hex");
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

export async function registerDevUser(input: {
  name: string;
  email: string;
  password: string;
}) {
  const users = await readUsers();
  const email = input.email.trim().toLowerCase();
  if (users.some((user) => user.email === email)) {
    throw new Error("Email already registered.");
  }

  const salt = randomBytes(16).toString("hex");
  const nextUser: StoredUser = {
    id: `dev-${Date.now().toString(36)}`,
    name: input.name.trim(),
    email,
    passwordHash: hashPassword(input.password, salt),
    salt,
    createdAt: new Date().toISOString(),
  };

  users.push(nextUser);
  await writeUsers(users);

  return {
    id: nextUser.id,
    name: nextUser.name,
    email: nextUser.email,
  };
}

export async function authenticateDevUser(emailInput: string, password: string) {
  const users = await readUsers();
  const email = emailInput.trim().toLowerCase();
  const user = users.find((row) => row.email === email);
  if (!user) return null;
  if (!verifyPassword(password, user.salt, user.passwordHash)) return null;

  return {
    id: user.id,
    name: user.name,
    email: user.email,
  };
}
