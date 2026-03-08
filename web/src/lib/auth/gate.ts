type AuthGateSnapshot = {
  authenticated: boolean;
};

let authGateSnapshot: AuthGateSnapshot | null = null;

export function getCachedAuthGate(): boolean {
  return Boolean(authGateSnapshot?.authenticated);
}

export function cacheAuthenticatedGate(): void {
  authGateSnapshot = {
    authenticated: true,
  };
}

export function invalidateAuthGate(): void {
  authGateSnapshot = null;
}
