import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  getAuthStatus,
  getMe,
  getToken,
  getUser as getStoredUser,
  login as loginApi,
  logout as logoutApi,
  moliliSmsVerify,
  refreshToken,
  register as registerApi,
  _writeToken,
  _clearTokens,
} from "@/core/auth/api";

import { swallow } from "@/core/utils/log";
import type {
  AuthStatus,
  LoginRequest,
  RegisterRequest,
  User,
} from "@/core/auth/types";
import { useI18n } from "@/core/i18n/hooks";

const GUEST_USER_ID = "__guest__";
const ANONYMOUS_USER_ID = "__anonymous__";

function isPlaceholderUsername(username?: string | null): boolean {
  const value = username?.trim().toLowerCase();
  return !value || value === "anonymous" || value === ANONYMOUS_USER_ID;
}

function isPlaceholderUserId(userId?: string | null): boolean {
  const value = userId?.trim().toLowerCase();
  return !value || value === "anonymous" || value === ANONYMOUS_USER_ID;
}

function userFromJwt(token: string | null): Partial<User> | null {
  if (!token || token === GUEST_USER_ID || token.split(".").length !== 3) {
    return null;
  }
  try {
    const tokenPayload = token.split(".")[1];
    if (!tokenPayload) return null;
    const rawPayload = tokenPayload.replace(/-/g, "+").replace(/_/g, "/");
    const payload = rawPayload.padEnd(
      Math.ceil(rawPayload.length / 4) * 4,
      "=",
    );
    const json = JSON.parse(window.atob(payload)) as {
      sub?: string;
      mobile?: string;
      provider?: string;
    };
    const actorId = json.sub;
    const mobile =
      json.mobile ||
      (actorId?.startsWith("molili:")
        ? actorId.slice("molili:".length)
        : undefined);
    if (!actorId && !mobile) return null;
    return {
      user_id: actorId || mobile,
      actor_id: actorId,
      username: mobile || actorId || "Octopus",
      mobile,
      provider: json.provider,
    };
  } catch (e) {
    swallow(e);
    return null;
  }
}

function normalizeUserIdentity(
  incoming: User,
  fallback?: Partial<User> | null,
  fallbackMobile?: string,
  credits?: Record<string, unknown> | null,
): User {
  const mobile = incoming.mobile || fallback?.mobile || fallbackMobile;
  const actorId = incoming.actor_id || fallback?.actor_id;
  const incomingUserId = !isPlaceholderUserId(incoming.user_id)
    ? incoming.user_id
    : undefined;
  const fallbackUserId = !isPlaceholderUserId(fallback?.user_id)
    ? fallback?.user_id
    : undefined;
  const userId =
    incomingUserId || actorId || fallbackUserId || mobile || ANONYMOUS_USER_ID;
  const fallbackUsername =
    fallback?.username && !isPlaceholderUsername(fallback.username)
      ? fallback.username
      : undefined;
  const username = isPlaceholderUsername(incoming.username)
    ? mobile ||
      incoming.email ||
      fallbackUsername ||
      incoming.username ||
      userId
    : incoming.username;

  return {
    ...fallback,
    ...incoming,
    user_id: userId,
    username,
    ...(actorId ? { actor_id: actorId } : {}),
    ...(mobile ? { mobile } : {}),
    ...(credits && Object.keys(credits).length > 0
      ? { molili_credits: credits }
      : {}),
  };
}

interface AuthContextType {
  isLoading: boolean;
  authStatus: AuthStatus | null;
  user: User | null;
  isAuthenticated: boolean;
  isGuest: boolean;
  login: (request: LoginRequest) => Promise<void>;
  smsLogin: (phone: string, code: string) => Promise<void>;
  guestLogin: () => Promise<void>;
  register: (request: RegisterRequest) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function _writeGuestState(guestUser: User): void {
  _writeToken(GUEST_USER_ID, guestUser);
}

function _clearGuestState(): void {
  _clearTokens();
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const [isLoading, setIsLoading] = useState(true);
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const initializedRef = useRef(false);

  const isAuthenticated =
    !!user && !isPlaceholderUserId(user.user_id) && !user.is_guest;
  const isGuest =
    !!user && (user.is_guest || isPlaceholderUserId(user.user_id));

  const bootstrapGuest = useCallback(() => {
    const guestUser: User = {
      user_id: GUEST_USER_ID,
      username: t.auth.guestUser,
      email: "",
      is_guest: true,
    };
    _writeGuestState(guestUser);
    setUser(guestUser);
  }, [t.auth.guestUser]);

  const initAuth = useCallback(async () => {
    const token = getToken();
    const storedUser = getStoredUser();
    const tokenUser = userFromJwt(token);
    const localUser = storedUser || tokenUser;
    if (token && token !== GUEST_USER_ID && localUser && !localUser.is_guest) {
      setUser(normalizeUserIdentity(localUser as User, tokenUser));
    } else if (storedUser?.is_guest && token === GUEST_USER_ID) {
      setUser(storedUser);
    } else {
      bootstrapGuest();
    }
    setIsLoading(false);

    try {
      const status = await getAuthStatus().catch(() => null);
      if (status) setAuthStatus(status);
      if (token && token !== GUEST_USER_ID) {
        try {
          const currentUser = await getMe();
          setUser(
            normalizeUserIdentity(
              currentUser,
              storedUser || tokenUser,
              undefined,
              undefined,
            ),
          );
        } catch (err) {
          swallow(err);
          const msg = err instanceof Error ? err.message : "";
          if (/401|Unauthorized/i.test(msg)) {
            _clearGuestState();
            bootstrapGuest();
          }
        }
      }
    } catch (e) {
      swallow(e);
    }
  }, [bootstrapGuest]);

  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    initAuth();
  }, [initAuth]);

  const login = useCallback(async (request: LoginRequest) => {
    const response = await loginApi(request);
    if (response.user) {
      const normalized = normalizeUserIdentity(response.user);
      if (response.access_token) _writeToken(response.access_token, normalized);
      setUser(normalized);
    }
  }, []);

  const smsLogin = useCallback(async (phone: string, code: string) => {
    const response = await moliliSmsVerify(phone, code);
    if (response.user) {
      const normalized = normalizeUserIdentity(
        response.user,
        null,
        phone,
        response.credits,
      );
      if (response.access_token) _writeToken(response.access_token, normalized);
      setUser(normalized);
    }
  }, []);

  const guestLogin = useCallback(async () => {
    const guestUser: User = {
      user_id: GUEST_USER_ID,
      username: t.auth.guestUser,
      email: "",
      is_guest: true,
    };
    _writeGuestState(guestUser);
    setUser(guestUser);
  }, [t.auth.guestUser]);

  const register = useCallback(async (request: RegisterRequest) => {
    const newUser = await registerApi(request);
    setUser(newUser);
  }, []);

  const logout = useCallback(async () => {
    await logoutApi();
    _clearGuestState();
    setUser(null);
  }, []);

  const refresh = useCallback(async () => {
    const response = await refreshToken();
    if (response.user) {
      setUser((previous) => {
        const normalized = normalizeUserIdentity(response.user!, previous);
        if (response.access_token)
          _writeToken(response.access_token, normalized);
        return normalized;
      });
    }
  }, []);

  const value = useMemo(
    () => ({
      isLoading,
      authStatus,
      user,
      isAuthenticated,
      isGuest,
      login,
      smsLogin,
      guestLogin,
      register,
      logout,
      refresh,
    }),
    [
      isLoading,
      authStatus,
      user,
      isAuthenticated,
      isGuest,
      login,
      smsLogin,
      guestLogin,
      register,
      logout,
      refresh,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
