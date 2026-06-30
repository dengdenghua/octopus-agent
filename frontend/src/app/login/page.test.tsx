/* Implementation note. */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderWithProviders } from "@/test/harness";

const navigateMock = vi.fn();
const smsSendMock = vi.fn();
const smsLoginMock = vi.fn();
const emailSendMock = vi.fn();
const emailLoginMock = vi.fn();
const getAuthProvidersMock = vi.fn();
const allowRegistrationMock = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<
    typeof import("react-router-dom") // eslint-disable-line @typescript-eslint/consistent-type-imports
  >("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("@/core/auth/api", () => ({
  getAuthProviderInfo: () => getAuthProvidersMock(),
  moliliSmsSend: (phone: string) => smsSendMock(phone),
  isMoliliDisabled: () => false,
  authHeaders: () => ({}),
  jsonAuthHeaders: () => ({}),
}));

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({
    smsLogin: (phone: string, code: string) => smsLoginMock(phone, code),
    emailLogin: (email: string, code: string) => emailLoginMock(email, code),
    guestLogin: vi.fn(),
    authStatus: { enabled: true, allow_registration: allowRegistrationMock() },
    isLoading: false,
    isAuthenticated: false,
    isGuest: false,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
  }),
}));

vi.mock("@/core/oct", () => ({
  octAuthApi: {
    emailSend: (email: string) => emailSendMock(email),
  },
  OctApiError: class OctApiError extends Error {
    status: number;
    constructor(message: string, status = 500) {
      super(message);
      this.status = status;
    }
  },
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

import LoginPage from "./page";

function expectTextContentIncludes(text: string) {
  expect(
    screen.getByText((_, node) => elementOwnsText(node, text)),
  ).toBeInTheDocument();
}

function elementOwnsText(node: Element | null, text: string): boolean {
  if (!node?.textContent?.includes(text)) return false;
  return Array.from(node.children).every(
    (child) => !child.textContent?.includes(text),
  );
}

function renderPage() {
  // Test strings reference zh-CN copy, so prime the I18nProvider with
  // zh-CN. The harness also pre-seeds the `locale` cookie so the
  // mount effect in `useI18n()` doesn't race back to the jsdom default.
  return renderWithProviders(<LoginPage />, {
    initialRoute: "/login",
    locale: "zh-CN",
  });
}

/* Implementation note. */
async function renderPageAtLoginForm() {
  const user = userEvent.setup();
  renderPage();

  // The login form is the landing surface · no onboarding stepper
  // to advance through. We just wait for the auth provider probe to
  // resolve so the SMS tab is rendered.
  await screen.findByRole("textbox", { name: "手机号" });

  return user;
}

describe("LoginPage", () => {
  beforeEach(() => {
    navigateMock.mockReset();
    smsSendMock.mockReset();
    smsLoginMock.mockReset();
    emailSendMock.mockReset();
    emailLoginMock.mockReset();
    getAuthProvidersMock.mockReset();
    allowRegistrationMock.mockReset();
    getAuthProvidersMock.mockResolvedValue([{ id: "molili" }]);
    allowRegistrationMock.mockReturnValue(false);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("defaults to the SMS tab with phone + code fields visible", async () => {
    await renderPageAtLoginForm();
    expect(screen.getByRole("textbox", { name: "手机号" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "验证码" })).toBeInTheDocument();
    // Legacy password tab was removed upstream · nothing here asks
    // for a password.
    expect(screen.queryByLabelText("密码")).not.toBeInTheDocument();
  });

  it("uses email-specific copy when Oct email auth is available", async () => {
    getAuthProvidersMock.mockResolvedValue([{ id: "oct" }]);

    renderPage();

    expect(await screen.findByText("邮箱验证码登录，自动绑定大模型与积分")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "邮箱" })).toBeInTheDocument();
    expectTextContentIncludes("未注册邮箱将自动创建账号");
    expect(screen.queryByText("手机号直接登录，自动绑定大模型与积分")).not.toBeInTheDocument();
    expect(screen.queryByText("未注册手机号将自动创建账号")).not.toBeInTheDocument();
  });

  it("uses email-specific registration copy outside the form too", async () => {
    getAuthProvidersMock.mockResolvedValue([{ id: "oct" }]);
    allowRegistrationMock.mockReturnValue(true);

    renderPage();

    expect(await screen.findByText("邮箱验证码登录，自动绑定大模型与积分")).toBeInTheDocument();
    expect(
      screen.getAllByText((_, node) =>
        elementOwnsText(node, "未注册邮箱将自动创建账号"),
      ),
    ).toHaveLength(2);
    expect(screen.queryByText("未注册手机号将自动创建账号")).not.toBeInTheDocument();
  });

  it("获取验证码 is enabled by default; invalid phone surfaces toast error", async () => {
    // Current behavior: send button is always enabled while idle ·
    // clicking with a bad phone fires a toast rather than disabling
    // the button up front (older versions had a length-gated button).
    const { toast } = await import("sonner");
    smsSendMock.mockResolvedValue({ sent: true });
    const user = await renderPageAtLoginForm();

    const sendBtn = screen.getByRole("button", { name: "获取验证码" });
    expect(sendBtn).not.toBeDisabled();

    // Too short · click produces a toast.error, no API hit.
    await user.type(screen.getByRole("textbox", { name: "手机号" }), "139");
    await user.click(sendBtn);
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(smsSendMock).not.toHaveBeenCalled();
  });

  it("sends the SMS code and kicks off cooldown on success", async () => {
    smsSendMock.mockResolvedValue({ sent: true });
    const user = await renderPageAtLoginForm();

    await user.type(
      screen.getByRole("textbox", { name: "手机号" }),
      "13800001111",
    );

    const sendBtn = screen.getByRole("button", { name: "获取验证码" });
    expect(sendBtn).not.toBeDisabled();
    await user.click(sendBtn);

    // API hit with the trimmed phone.
    await waitFor(() =>
      expect(smsSendMock).toHaveBeenCalledWith("13800001111"),
    );

    // Implementation note.
    // · assert the original label is gone.
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "获取验证码" }),
      ).not.toBeInTheDocument();
    });
  });

  it("calls smsLogin and navigates on successful verify", async () => {
    smsLoginMock.mockResolvedValue(undefined);
    const user = await renderPageAtLoginForm();

    await user.type(
      screen.getByRole("textbox", { name: "手机号" }),
      "13800001111",
    );
    await user.type(screen.getByRole("textbox", { name: "验证码" }), "123456");

    // Implementation note.
    // Implementation note.
    await user.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => {
      expect(smsLoginMock).toHaveBeenCalledWith("13800001111", "123456");
    });
    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith("/workspace");
    });
  });

  it("surfaces upstream error via toast (no navigation)", async () => {
    const { toast } = await import("sonner");
    smsLoginMock.mockRejectedValue(new Error("验证码已过期"));
    const user = await renderPageAtLoginForm();

    await user.type(
      screen.getByRole("textbox", { name: "手机号" }),
      "13800001111",
    );
    await user.type(screen.getByRole("textbox", { name: "验证码" }), "000000");
    await user.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("验证码已过期");
    });
    expect(navigateMock).not.toHaveBeenCalled();
  });
});
