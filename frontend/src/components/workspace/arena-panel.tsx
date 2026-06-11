/**
 * Arena Panel — blind A/B model comparison.
 *
 * Features:
 *  - Split-screen side-by-side response comparison
 *  - Model names hidden until user votes
 *  - Vote buttons: A is better, B is better, Tie, Both bad
 *  - Post-vote reveal with model names
 *  - ELO leaderboard tab
 */

import {
  CrownIcon,
  Loader2Icon,
  SendIcon,
  SwordsIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  TrophyIcon,
  XIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  createBattle,
  fetchLeaderboard,
  submitVote,
} from "@/core/arena/api";
import type {
  BattleResponse,
  LeaderboardEntry,
  VoteChoice,
  VoteResponse,
} from "@/core/arena/types";
import { swallow } from "@/core/utils/log";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ArenaPhase = "idle" | "loading" | "battle" | "voted";

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ArenaPanel({ onClose }: { onClose?: () => void }) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<ArenaPhase>("idle");
  const [prompt, setPrompt] = useState("");
  const [battle, setBattle] = useState<BattleResponse | null>(null);
  const [voteResult, setVoteResult] = useState<VoteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("battle");

  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Focus input on mount
  useEffect(() => {
    if (phase === "idle") inputRef.current?.focus();
  }, [phase]);

  const handleStartBattle = useCallback(async () => {
    const trimmed = prompt.trim();
    if (!trimmed) return;

    setPhase("loading");
    setError(null);
    setBattle(null);
    setVoteResult(null);

    try {
      const result = await createBattle({ prompt: trimmed });
      setBattle(result);
      setPhase("battle");
    } catch (e) {
      swallow(e);
      setError(e instanceof Error ? e.message : String(e));
      setPhase("idle");
    }
  }, [prompt]);

  const handleVote = useCallback(
    async (vote: VoteChoice) => {
      if (!battle) return;
      try {
        const result = await submitVote(battle.session_id, vote);
        setVoteResult(result);
        setPhase("voted");
      } catch (e) {
        swallow(e);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [battle],
  );

  const handleNewBattle = useCallback(() => {
    setPhase("idle");
    setPrompt("");
    setBattle(null);
    setVoteResult(null);
    setError(null);
  }, []);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b px-4 py-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <SwordsIcon className="text-primary size-5" />
            <h2 className="text-lg font-semibold">{t.arena.title}</h2>
            <span className="bg-primary/10 text-primary rounded-lg px-2 py-0.5 text-xs font-medium">
              {t.arena.blindAB}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {onClose && (
              <Button variant="ghost" size="icon-sm" onClick={onClose}>
                <XIcon className="size-4" />
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex min-h-0 flex-1 flex-col">
        <div className="border-b px-4">
          <TabsList variant="line">
            <TabsTrigger value="battle">
              <SwordsIcon className="mr-1.5 size-3.5" />
              {t.arena.battle}
            </TabsTrigger>
            <TabsTrigger value="leaderboard">
              <TrophyIcon className="mr-1.5 size-3.5" />
              {t.arena.leaderboard}
            </TabsTrigger>
          </TabsList>
        </div>

        {/* Battle Tab */}
        <TabsContent value="battle" className="mt-0 flex min-h-0 flex-1 flex-col overflow-hidden">
          {phase === "idle" && (
            <IdleView
              ref={inputRef}
              prompt={prompt}
              error={error}
              onPromptChange={setPrompt}
              onSubmit={handleStartBattle}
            />
          )}

          {phase === "loading" && <LoadingView prompt={prompt} />}

          {phase === "battle" && battle && (
            <BattleView battle={battle} onVote={handleVote} error={error} />
          )}

          {phase === "voted" && voteResult && (
            <VotedView result={voteResult} onNewBattle={handleNewBattle} />
          )}
        </TabsContent>

        {/* Leaderboard Tab */}
        <TabsContent value="leaderboard" className="mt-0 flex min-h-0 flex-1 flex-col overflow-auto">
          <LeaderboardView />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Idle View — prompt input
// ---------------------------------------------------------------------------

import { forwardRef } from "react";

const IdleView = forwardRef<
  HTMLTextAreaElement,
  {
    prompt: string;
    error: string | null;
    onPromptChange: (v: string) => void;
    onSubmit: () => void;
  }
>(function IdleView({ prompt, error, onPromptChange, onSubmit }, ref) {
  const { t } = useI18n();
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 p-6">
      <div className="text-center">
        <SwordsIcon className="text-muted-foreground mx-auto mb-3 size-12 opacity-40" />
        <h3 className="text-lg font-semibold">{t.arena.battle}</h3>
        <p className="text-muted-foreground mt-1 max-w-md text-sm">
          {t.arena.battleDesc}
        </p>
      </div>

      {error && (
        <div className="bg-destructive/10 text-destructive w-full max-w-lg rounded-lg px-4 py-2 text-sm">
          {error}
        </div>
      )}

      <div className="w-full max-w-lg">
        <div className="border-input focus-within:border-primary/50 focus-within:ring-ring/20 flex items-end gap-2 rounded-lg border p-2 shadow-sm focus-within:ring-2">
          <textarea
            ref={ref}
            value={prompt}
            onChange={(e) => onPromptChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSubmit();
              }
            }}
            placeholder={t.arena.promptPlaceholder}
            className="min-h-[60px] flex-1 resize-none border-0 bg-transparent p-2 text-sm outline-none placeholder:text-muted-foreground"
            rows={3}
          />
          <Button
            size="icon"
            onClick={onSubmit}
            disabled={!prompt.trim()}
            className="shrink-0"
          >
            <SendIcon className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------------
// Loading View
// ---------------------------------------------------------------------------

function LoadingView({ prompt }: { prompt: string }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-6">
      <Loader2Icon className="text-primary size-8 animate-spin" />
      <div className="text-center">
        <p className="font-medium">{t.arena.battleInProgress}</p>
        <p className="text-muted-foreground mt-1 text-sm">
          {t.arena.sendingPrompt}
        </p>
      </div>
      <div className="bg-muted max-w-md rounded-lg p-3">
        <p className="text-muted-foreground text-xs">{t.arena.prompt}:</p>
        <p className="mt-1 text-sm">{prompt}</p>
      </div>
      {/* Two-column skeleton preview */}
      <div className="flex gap-4 p-4">
        <div className="flex-1 space-y-3">
          <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
          <div className="h-4 w-full animate-pulse rounded bg-muted" />
          <div className="h-4 w-5/6 animate-pulse rounded bg-muted" />
          <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
        </div>
        <div className="flex-1 space-y-3">
          <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
          <div className="h-4 w-full animate-pulse rounded bg-muted" />
          <div className="h-4 w-5/6 animate-pulse rounded bg-muted" />
          <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Battle View — side-by-side responses with vote buttons
// ---------------------------------------------------------------------------

function BattleView({
  battle,
  onVote,
  error,
}: {
  battle: BattleResponse;
  onVote: (v: VoteChoice) => void;
  error: string | null;
}) {
  const { t } = useI18n();
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Prompt display */}
      <div className="border-b px-4 py-2.5">
        <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
          {t.arena.prompt}
        </p>
        <p className="mt-0.5 text-sm">{battle.prompt}</p>
      </div>

      {/* Side-by-side responses */}
      <div className="grid min-h-0 flex-1 grid-cols-2 divide-x overflow-hidden">
        <ResponseColumn
          label={t.arena.modelA}
          response={battle.response_a}
          latencyMs={battle.latency_a_ms}
          color="blue"
        />
        <ResponseColumn
          label={t.arena.modelB}
          response={battle.response_b}
          latencyMs={battle.latency_b_ms}
          color="orange"
        />
      </div>

      {/* Vote buttons */}
      <div className="border-t px-4 py-3">
        {error && (
          <p className="text-destructive mb-2 text-center text-sm">{error}</p>
        )}
        <p className="text-muted-foreground mb-2 text-center text-xs">
          {t.arena.whichBetter}
        </p>
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onVote("a")}
            className="border-blue-300 dark:border-blue-700 hover:border-blue-500 hover:bg-blue-50 dark:hover:bg-blue-950 focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ThumbsUpIcon className="mr-1.5 size-3.5 text-blue-500" />
            {t.arena.aIsBetter}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onVote("b")}
            className="border-orange-300 dark:border-orange-700 hover:border-orange-500 hover:bg-orange-50 dark:hover:bg-orange-950 focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ThumbsUpIcon className="mr-1.5 size-3.5 text-orange-500" />
            {t.arena.bIsBetter}
          </Button>
          <Button variant="outline" size="sm" onClick={() => onVote("tie")} className="focus-visible:ring-2 focus-visible:ring-ring">
            {t.arena.tie}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onVote("both_bad")}
            className="focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ThumbsDownIcon className="mr-1.5 size-3.5" />
            {t.arena.bothBad}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Response Column
// ---------------------------------------------------------------------------

function ResponseColumn({
  label,
  response,
  latencyMs,
  color,
  modelName,
}: {
  label: string;
  response: string;
  latencyMs: number | null;
  color: "blue" | "orange";
  modelName?: string;
}) {
  const colorClasses =
    color === "blue"
      ? "bg-blue-500/10 text-blue-700 dark:text-blue-300"
      : "bg-orange-500/10 text-orange-700 dark:text-orange-300";

  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className={cn("rounded-lg px-2 py-0.5 text-xs font-semibold", colorClasses)}>
          {label}
        </span>
        <div className="flex items-center gap-2">
          {modelName && (
            <span className="bg-muted rounded px-1.5 py-0.5 text-xs font-medium">
              {modelName}
            </span>
          )}
          {latencyMs != null && (
            <span className="text-muted-foreground text-xs">
              {(latencyMs / 1000).toFixed(1)}s
            </span>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-auto p-3">
        <div className="prose dark:prose-invert prose-sm max-w-none whitespace-pre-wrap text-sm">
          {response}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Voted View — reveals model names
// ---------------------------------------------------------------------------

function VotedView({
  result,
  onNewBattle,
}: {
  result: VoteResponse;
  onNewBattle: () => void;
}) {
  const { t } = useI18n();
  const voteLabels: Record<string, string> = {
    a: t.arena.choseA,
    b: t.arena.choseB,
    tie: t.arena.votedTie,
    both_bad: t.arena.votedBothBad,
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Vote result banner */}
      <div className="bg-primary/5 border-b px-4 py-2.5 text-center">
        <p className="text-sm font-medium">
          {voteLabels[result.vote] ?? t.arena.voted}
        </p>
        <p className="text-muted-foreground mt-0.5 text-xs">
          {t.arena.identitiesRevealed}
        </p>
      </div>

      {/* Prompt */}
      <div className="border-b px-4 py-2.5">
        <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
          {t.arena.prompt}
        </p>
        <p className="mt-0.5 text-sm">{result.prompt}</p>
      </div>

      {/* Side-by-side with revealed names */}
      <div className="grid min-h-0 flex-1 grid-cols-2 divide-x overflow-hidden">
        <ResponseColumn
          label={t.arena.modelA}
          response={result.response_a}
          latencyMs={result.latency_a_ms}
          color="blue"
          modelName={result.model_a}
        />
        <ResponseColumn
          label={t.arena.modelB}
          response={result.response_b}
          latencyMs={result.latency_b_ms}
          color="orange"
          modelName={result.model_b}
        />
      </div>

      {/* New battle button */}
      <div className="border-t px-4 py-3 text-center">
        <Button onClick={onNewBattle} size="sm">
          <SwordsIcon className="mr-1.5 size-3.5" />
          {t.arena.newBattle}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Leaderboard View
// ---------------------------------------------------------------------------

function LeaderboardView() {
  const { t } = useI18n();
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchLeaderboard()
      .then((res) => {
        if (!cancelled) {
          setEntries(res.entries);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2Icon className="text-muted-foreground size-6 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <p className="text-destructive text-sm">{error}</p>
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6">
        <TrophyIcon className="text-muted-foreground size-10 opacity-30" />
        <p className="text-muted-foreground text-sm">
          {t.arena.noBattles}
        </p>
      </div>
    );
  }

  return (
    <div className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <TrophyIcon className="text-primary size-4" />
        <h3 className="font-semibold">{t.arena.eloLeaderboard}</h3>
        <span className="text-muted-foreground text-xs">
          ({entries.length} models)
        </span>
      </div>

      <div className="overflow-hidden rounded-lg border">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-muted/50 border-b">
              <th className="px-3 py-2 text-left font-medium">#</th>
              <th className="px-3 py-2 text-left font-medium">{t.arena.model}</th>
              <th className="px-3 py-2 text-right font-medium">{t.arena.elo}</th>
              <th className="px-3 py-2 text-right font-medium">{t.arena.winRate}</th>
              <th className="px-3 py-2 text-right font-medium">{t.arena.wins}</th>
              <th className="px-3 py-2 text-right font-medium">{t.arena.losses}</th>
              <th className="px-3 py-2 text-right font-medium">{t.arena.ties}</th>
              <th className="px-3 py-2 text-right font-medium">{t.arena.battles}</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr
                key={entry.model_name}
                className="hover:bg-muted/30 border-b last:border-0"
              >
                <td className="px-3 py-2">
                  {entry.rank <= 3 ? (
                    <CrownIcon
                      className={cn(
                        "size-4",
                        entry.rank === 1 && "text-yellow-500",
                        entry.rank === 2 && "text-gray-400",
                        entry.rank === 3 && "text-amber-700",
                      )}
                    />
                  ) : (
                    <span className="text-muted-foreground">{entry.rank}</span>
                  )}
                </td>
                <td className="px-3 py-2 font-medium">{entry.model_name}</td>
                <td className="px-3 py-2 text-right font-mono">
                  {Math.round(entry.rating)}
                </td>
                <td className="px-3 py-2 text-right">
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-xs font-medium",
                      entry.win_rate >= 60
                        ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                        : entry.win_rate >= 40
                          ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400"
                          : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
                    )}
                  >
                    {entry.win_rate.toFixed(1)}%
                  </span>
                </td>
                <td className="text-muted-foreground px-3 py-2 text-right">
                  {entry.wins}
                </td>
                <td className="text-muted-foreground px-3 py-2 text-right">
                  {entry.losses}
                </td>
                <td className="text-muted-foreground px-3 py-2 text-right">
                  {entry.ties}
                </td>
                <td className="text-muted-foreground px-3 py-2 text-right">
                  {entry.battles}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
