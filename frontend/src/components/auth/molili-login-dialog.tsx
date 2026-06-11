/* Implementation note. */

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRightIcon, ShieldCheckIcon } from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { moliliSmsSend, isMoliliDisabled } from "@/core/auth/api";
import { useAuth } from "@/providers/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

const SMS_COOLDOWN_SECONDS = 60;

function isValidCnPhone(raw: string): boolean {
  const cleaned = raw.trim();
  const digits = cleaned.replace(/\D/g, "");
  return /^1\d{10}$/.test(digits) || digits.length >= 7;
}

function normalizePhone(raw: string): string {
  const cleaned = raw.trim();
  if (cleaned.startsWith("+")) {
    return "+" + cleaned.slice(1).replace(/\D/g, "");
  }
  return cleaned.replace(/\D/g, "");
}

export function MoliliLoginDialog() {
  const { smsLogin } = useAuth();
  const queryClient = useQueryClient();
  const { t } = useI18n();

  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<string | undefined>(undefined);
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sending, setSending] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Listen for the global open trigger.
  useEffect(() => {
    const handler = (e: Event) => {
      const custom = e as CustomEvent<{ reason?: string }>;
      setReason(custom.detail?.reason);
      setOpen(true);
    };
    window.addEventListener("octopus:open-molili-login", handler);
    return () => window.removeEventListener("octopus:open-molili-login", handler);
  }, []);

  // Cooldown timer for the resend button.
  useEffect(() => {
    if (cooldown <= 0) return;
    tickRef.current = setInterval(() => {
      setCooldown((s) => Math.max(0, s - 1));
    }, 1000);
    return () => {
      if (tickRef.current) clearInterval(tickRef.current);
    };
  }, [cooldown]);

  // Reset form state whenever the dialog re-opens so stale values don't
  // leak across sessions.
  useEffect(() => {
    if (!open) {
      setCode("");
      setSubmitting(false);
    }
  }, [open]);

  const sendCode = useCallback(async () => {
    const normalizedPhone = normalizePhone(phone);
    if (!isValidCnPhone(normalizedPhone)) {
      toast.error(t.auth.errors.invalidPhone);
      return;
    }
    setSending(true);
    try {
      const res = await moliliSmsSend(normalizedPhone);
      // Dev convenience: when the backend runs in mock mode with
      // `mock_code` configured, it echoes the verification code back
      // as `upstream.code_for_dev`. Auto-fill it so the user doesn't
      // have to hunt through server logs.
      const devCode = (res as { upstream?: { code_for_dev?: string | null } })
        ?.upstream?.code_for_dev;
      if (devCode) {
        setCode(devCode);
        toast.success(`${t.auth.success.codeSent} · Mock code: ${devCode}`);
      } else {
        toast.success(t.auth.success.codeSent);
      }
      setCooldown(SMS_COOLDOWN_SECONDS);
    } catch (err) {
      if (isMoliliDisabled(err)) {
        toast.error(t.auth.errors.moliliNotEnabled);
        setOpen(false);
      } else {
        toast.error(err instanceof Error ? err.message : t.auth.errors.sendFailed);
      }
    } finally {
      setSending(false);
    }
  }, [phone, t]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const normalizedPhone = normalizePhone(phone);
      if (!normalizedPhone || !code) {
        toast.error(t.auth.errors.fillRequired);
        return;
      }
      if (!isValidCnPhone(normalizedPhone)) {
        toast.error(t.auth.errors.invalidPhone);
        return;
      }
      setSubmitting(true);
      try {
        await smsLogin(normalizedPhone, code.trim());
        toast.success(t.auth.success.loginSuccess);
        // Only invalidate essential queries to speed up login.
        // Models and user info will be fetched on demand.
        queryClient.invalidateQueries({ queryKey: ["user"] });
        queryClient.invalidateQueries({ queryKey: ["models"] });
        setOpen(false);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t.auth.errors.loginFailed);
      } finally {
        setSubmitting(false);
      }
    },
    [phone, code, smsLogin, queryClient, t],
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <ShieldCheckIcon className="size-3.5 text-violet-500" />
            {t.auth.loginAccount}
          </div>
          <DialogTitle className="text-lg">{t.auth.molili.title}</DialogTitle>
          <DialogDescription>
            {reason ?? t.auth.molili.reason}
            <span className="text-muted-foreground/80 ml-1">
              {t.auth.molili.autoRegister}
            </span>
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="molili-phone">{t.auth.phoneNumber}</Label>
            <Input
              id="molili-phone"
              type="tel"
              placeholder={t.auth.placeholders.phone}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              autoComplete="tel"
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="molili-code">{t.auth.verificationCode}</Label>
            <div className="flex gap-2">
              <Input
                id="molili-code"
                type="text"
                inputMode="numeric"
                placeholder={t.auth.placeholders.code}
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
              <Button
                type="button"
                variant="outline"
                onClick={sendCode}
                disabled={sending || cooldown > 0}
                className="shrink-0"
              >
                {cooldown > 0 ? `${cooldown}s` : sending ? t.auth.sending : t.auth.sendCode}
              </Button>
            </div>
          </div>
          <Button
            type="submit"
            className="w-full bg-gradient-to-r from-purple-500 to-blue-500 hover:brightness-110"
            disabled={submitting}
          >
            {submitting ? t.auth.loggingIn : t.auth.login}
            {!submitting && <ArrowRightIcon className="size-4" />}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
