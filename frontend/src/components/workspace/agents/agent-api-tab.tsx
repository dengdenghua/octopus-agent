/** Agent API Tab
 *
 * Preview-only · the backend publish endpoint (``POST /api/agents/:id/api``
 * and its companion unpublish + key-issue endpoints) isn't implemented yet,
 * so we don't ship the publish toggle · clicking it previously generated a
 * mock ``octo_xxx`` key that did nothing except mislead users.
 *
 * When the backend lands, restore the toggle + real mutation from git
 * history and drop the ``comingSoon`` banner. The curl / python / js
 * examples are already shaped against the planned endpoint contract.
 */

import { useCallback } from "react";
import {
  CodeIcon,
  ConstructionIcon,
  CopyIcon,
  GlobeIcon,
  TerminalIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { copyTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import type { AgentWorldAgent } from "@/core/agents/types";

interface AgentApiTabProps {
  agent: AgentWorldAgent;
}

export function AgentApiTab({ agent }: AgentApiTabProps) {
  const { t } = useI18n();

  const baseUrl = typeof window !== "undefined" ? window.location.origin : "";
  const apiEndpoint = `${baseUrl}/api/agents/${agent.name}/run`;

  const curlExample = `curl -X POST "${apiEndpoint}" \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{
    "message": "Hello, how can you help me?",
    "context": {},
    "stream": false
  }'`;

  const pythonExample = `import requests

response = requests.post(
    "${apiEndpoint}",
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer YOUR_API_KEY"
    },
    json={
        "message": "Hello, how can you help me?",
        "context": {},
        "stream": False
    }
)

result = response.json()
print(result["response"])`;

  const javascriptExample = `const response = await fetch("${apiEndpoint}", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": "Bearer YOUR_API_KEY"
  },
  body: JSON.stringify({
    message: "Hello, how can you help me?",
    context: {},
    stream: false
  })
});

const result = await response.json();
console.log(result.response);`;

  const copyToClipboard = useCallback(
    async (text: string) => {
      try {
        await copyTextToClipboard(text);
        toast.success(t.common.copied);
      } catch {
        toast.error(t.clipboard.failedToCopyToClipboard);
      }
    },
    [t.common.copied, t.clipboard.failedToCopyToClipboard],
  );

  return (
    <div className="space-y-5 py-2">
      {/* Header · feature description */}
      <div className="rounded-lg border p-4">
        <div className="flex items-center gap-2">
          <GlobeIcon className="text-primary h-5 w-5" />
          <h3 className="font-medium">{t.agentApi.title}</h3>
        </div>
        <p className="text-muted-foreground mt-1 text-sm">
          {t.agentApi.description}
        </p>
      </div>

      {/* Coming-soon banner · replaces the non-functional publish toggle */}
      <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
        <ConstructionIcon className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
        <div className="space-y-1">
          <div className="text-sm font-medium text-amber-700 dark:text-amber-300">
            {t.agentApi.comingSoonTitle}
          </div>
          <p className="text-muted-foreground text-xs">
            {t.agentApi.comingSoonDesc}
          </p>
        </div>
      </div>

      {/* Planned endpoint · read-only preview */}
      <div className="space-y-2">
        <Label className="text-sm">{t.agentApi.plannedEndpoint}</Label>
        <div className="flex gap-2">
          <Input value={apiEndpoint} readOnly className="font-mono text-sm" />
          <Button
            variant="outline"
            size="icon"
            onClick={() => copyToClipboard(apiEndpoint)}
            aria-label={t.common.copy}
          >
            <CopyIcon className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Sample calls · informational */}
      <div className="space-y-3">
        <Label className="text-sm">{t.agentApi.sampleCalls}</Label>
        <Tabs defaultValue="curl">
          <TabsList className="w-full justify-start">
            <TabsTrigger value="curl" className="gap-1">
              <TerminalIcon className="h-3.5 w-3.5" />
              cURL
            </TabsTrigger>
            <TabsTrigger value="python" className="gap-1">
              <CodeIcon className="h-3.5 w-3.5" />
              Python
            </TabsTrigger>
            <TabsTrigger value="javascript" className="gap-1">
              <CodeIcon className="h-3.5 w-3.5" />
              JavaScript
            </TabsTrigger>
          </TabsList>

          <TabsContent value="curl" className="mt-2">
            <div className="relative">
              <pre className="bg-muted rounded-lg p-3 overflow-x-auto text-xs font-mono">
                <code>{curlExample}</code>
              </pre>
              <Button
                variant="ghost"
                size="sm"
                className="absolute top-2 right-2"
                onClick={() => copyToClipboard(curlExample)}
                aria-label={t.common.copy}
              >
                <CopyIcon className="h-3 w-3" />
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="python" className="mt-2">
            <div className="relative">
              <pre className="bg-muted rounded-lg p-3 overflow-x-auto text-xs font-mono">
                <code>{pythonExample}</code>
              </pre>
              <Button
                variant="ghost"
                size="sm"
                className="absolute top-2 right-2"
                onClick={() => copyToClipboard(pythonExample)}
                aria-label={t.common.copy}
              >
                <CopyIcon className="h-3 w-3" />
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="javascript" className="mt-2">
            <div className="relative">
              <pre className="bg-muted rounded-lg p-3 overflow-x-auto text-xs font-mono">
                <code>{javascriptExample}</code>
              </pre>
              <Button
                variant="ghost"
                size="sm"
                className="absolute top-2 right-2"
                onClick={() => copyToClipboard(javascriptExample)}
                aria-label={t.common.copy}
              >
                <CopyIcon className="h-3 w-3" />
              </Button>
            </div>
          </TabsContent>
        </Tabs>
      </div>

      {/* Request format · informational */}
      <div className="space-y-2">
        <Label className="text-sm">{t.agentApi.requestFormat}</Label>
        <div className="bg-muted rounded-lg p-3 text-xs font-mono">
          <p className="text-muted-foreground">POST {apiEndpoint}</p>
          <p className="mt-2 text-green-600">{"{"}</p>
          <p className="pl-4">"message": "...",</p>
          <p className="pl-4">"context": {"{}"},</p>
          <p className="pl-4">"stream": false</p>
          <p className="text-green-600">{"}"}</p>
        </div>
      </div>
    </div>
  );
}
