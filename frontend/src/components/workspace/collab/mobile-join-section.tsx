import { useQuery } from "@tanstack/react-query";
import { CheckIcon, CopyIcon, SmartphoneIcon } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { authHeaders } from "@/core/auth/api";
import { copyTextToClipboard } from "@/core/clipboard";
import { getBackendBaseURL } from "@/core/config";

interface JoinInfo {
  lan_ip: string;
  ws_port: number;
  ws_url: string;
  token: string;
  connect_string: string;
}

/** "拉手机进群" — shows a scan-to-join QR + a paste-able 口令 so a phone running
 * octopus-mobile can connect to this gateway without typing an IP. */
export function MobileJoinSection() {
  const [copied, setCopied] = useState(false);
  const { data } = useQuery({
    queryKey: ["tentacle-join-info"],
    queryFn: async ({ signal }): Promise<JoinInfo | null> => {
      try {
        const res = await fetch(
          `${getBackendBaseURL()}/api/tentacle/join-info`,
          {
            headers: authHeaders(),
            signal,
          },
        );
        if (!res.ok) return null;
        return (await res.json()) as JoinInfo;
      } catch {
        return null;
      }
    },
    refetchOnWindowFocus: false,
    staleTime: 60_000,
  });

  // Bridge offline / not mounted → don't render the section at all.
  if (!data) return null;

  const handleCopy = async () => {
    try {
      await copyTextToClipboard(data.connect_string);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  };

  return (
    <section className="min-w-0 rounded-lg border border-border/60 bg-muted/10 p-3">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <SmartphoneIcon className="size-4 text-primary" />
        拉手机进群
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">
        手机装 octopus-mobile,扫码或粘贴口令即可连进群(需在同一 Wi-Fi)
      </div>

      <div className="mt-3 flex items-start gap-3">
        <div className="shrink-0 rounded-lg bg-white p-2">
          <QRCodeSVG value={data.connect_string} size={104} />
        </div>
        <div className="min-w-0 flex-1 space-y-2">
          <div>
            <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              连接口令(手机设置里粘贴)
            </div>
            <div className="flex gap-2">
              <code className="min-w-0 flex-1 truncate rounded-md border border-border/60 bg-background px-2 py-1.5 text-[11px]">
                {data.connect_string}
              </code>
              <Button
                onClick={handleCopy}
                variant="outline"
                size="icon"
                className="shrink-0"
              >
                {copied ? (
                  <CheckIcon className="size-4" />
                ) : (
                  <CopyIcon className="size-4" />
                )}
              </Button>
            </div>
          </div>
          <div className="text-[11px] leading-relaxed text-muted-foreground">
            或手动填:地址 <code className="text-foreground">{data.ws_url}</code>
            {data.token ? (
              <>
                {" "}
                · 口令 <code className="text-foreground">{data.token}</code>
              </>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
