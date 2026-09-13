export interface StoredTokenProfile {
  profile_id: string;
  token: string;
  environment: string;
  scopes: string[];
  expires_at: number | null;
  last_used_at: number | null;
  revoked: boolean;
}

const globalStore = globalThis as unknown as {
  __ironcore_token_profiles__?: Map<string, StoredTokenProfile>;
};

if (!globalStore.__ironcore_token_profiles__) {
  globalStore.__ironcore_token_profiles__ = new Map();
}

const profilesMap = globalStore.__ironcore_token_profiles__;

export function getAllTokenProfiles() {
  const nowSec = Math.floor(Date.now() / 1000);
  return Array.from(profilesMap.values()).map((p) => {
    const expired = p.expires_at ? nowSec > p.expires_at : false;
    const expiring_soon = p.expires_at ? !expired && p.expires_at - nowSec < 86400 * 3 : false;
    return {
      profile_id: p.profile_id,
      environment: p.environment,
      scopes: p.scopes,
      expires_at: p.expires_at,
      last_used_at: p.last_used_at,
      revoked: p.revoked,
      expired,
      expiring_soon,
      has_token: Boolean(p.token),
    };
  });
}

export function saveTokenProfile(input: {
  profile_id: string;
  token: string;
  environment?: string;
  scopes?: string[];
  expires_in_days?: number;
}) {
  const nowSec = Math.floor(Date.now() / 1000);
  const expires_at = input.expires_in_days && input.expires_in_days > 0
    ? nowSec + input.expires_in_days * 86400
    : null;

  const profile: StoredTokenProfile = {
    profile_id: input.profile_id,
    token: input.token,
    environment: input.environment || "cloud",
    scopes: input.scopes || [],
    expires_at,
    last_used_at: null,
    revoked: false,
  };

  profilesMap.set(input.profile_id, profile);
  return profile;
}

export function activateTokenProfile(profile_id: string) {
  const found = profilesMap.get(profile_id);
  if (!found || found.revoked) return null;
  found.last_used_at = Math.floor(Date.now() / 1000);
  return found.token;
}

export function revokeTokenProfile(profile_id: string) {
  const found = profilesMap.get(profile_id);
  if (found) {
    found.revoked = true;
    profilesMap.delete(profile_id);
    return true;
  }
  return false;
}
