/* Implementation note. */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  BrainIcon,
  Loader2Icon,
  NetworkIcon,
  RefreshCwIcon,
  SearchIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { getBackendBaseURL } from "@/core/config";
import { authHeaders } from "@/core/auth/api";
import { useI18n } from "@/core/i18n/hooks";
import { KnowledgeGraphView } from "./knowledge-graph-view";

interface KGEntity {
  id: string;
  name: string;
  entity_type: string;
  description: string;
}

interface KGRelationship {
  id: string;
  source_name: string;
  target_name: string;
  relationship_type: string;
}

interface GraphStats {
  total_entities: number;
  total_relationships: number;
  entity_types: Record<string, number>;
}

export function KnowledgeGraphPanel() {
  const { t } = useI18n();
  const [entities, setEntities] = useState<KGEntity[]>([]);
  const [relationships, setRelationships] = useState<KGRelationship[]>([]);
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [viewMode, setViewMode] = useState<"graph" | "list">("graph");

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [entitiesRes, statsRes] = await Promise.all([
        fetch(`${getBackendBaseURL()}/api/knowledge/graph?limit=100`, {
          headers: authHeaders(),
        }),
        fetch(`${getBackendBaseURL()}/api/knowledge/stats`, {
          headers: authHeaders(),
        }),
      ]);

      if (!entitiesRes.ok || !statsRes.ok) {
        throw new Error("Failed to fetch knowledge graph");
      }

      const entitiesData = await entitiesRes.json();
      const statsData = await statsRes.json();

      setEntities(entitiesData.entities || []);
      setRelationships(entitiesData.relationships || []);
      setStats(statsData);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.knowledgeGraph.loadFailed);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const filteredEntities = entities.filter(
    (e) =>
      e.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      e.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2Icon className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Empty state · KG booted fresh with zero entities. Without this
  // the page renders 3 zero-count cards + an empty list · no hint
  // that the extractor hasn't had source material yet.
  if (
    entities.length === 0 &&
    relationships.length === 0 &&
    !searchQuery
  ) {
    return (
      <div className="flex min-h-48 flex-col items-center justify-center gap-3 px-4 py-10 text-center">
        <div className="rounded-xl bg-gradient-to-br from-violet-500/10 to-purple-500/5 p-3 text-violet-600 dark:text-violet-400">
          <BrainIcon className="h-5 w-5" />
        </div>
        <div className="space-y-1">
          <div className="font-medium">{t.knowledgeGraph.emptyStateTitle}</div>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <Button asChild size="sm">
            <Link to="/workspace/realtime/new">开始一次任务</Link>
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void loadData()}
          >
            <RefreshCwIcon className="mr-1.5 h-3.5 w-3.5" />
            刷新
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Implementation note. */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setViewMode("graph")}
          className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${viewMode === "graph" ? "bg-violet-500/15 text-violet-400" : "text-muted-foreground hover:bg-muted"}`}
        >
          <NetworkIcon className="mr-1 inline size-3.5" />
          {t.knowledgePanel.graphView}
        </button>
        <button
          onClick={() => setViewMode("list")}
          className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${viewMode === "list" ? "bg-violet-500/15 text-violet-400" : "text-muted-foreground hover:bg-muted"}`}
        >
          <BrainIcon className="mr-1 inline size-3.5" />
          {t.knowledgePanel.listView}
        </button>
      </div>

      {viewMode === "graph" ? (
        <KnowledgeGraphView />
      ) : (
      <>
      {/* Implementation note. */}
      {stats && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {t.knowledgeGraph.totalEntities}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.total_entities}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {t.knowledgeGraph.totalRelationships}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {stats.total_relationships}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {t.knowledgeGraph.entityTypesCount}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {Object.keys(stats.entity_types).length}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Implementation note. */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <SearchIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={t.knowledgeGraph.searchPlaceholder}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
        <Button variant="outline" size="icon" onClick={() => void loadData()}>
          <RefreshCwIcon className="h-4 w-4" />
        </Button>
      </div>

      {/* Implementation note. */}
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {filteredEntities.map((entity) => (
          <Card key={entity.id}>
            <CardHeader className="pb-2">
              <div className="flex items-center gap-2">
                <BrainIcon className="h-4 w-4 text-primary" />
                <CardTitle className="text-base">{entity.name}</CardTitle>
              </div>
              <Badge variant="secondary">{entity.entity_type}</Badge>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground line-clamp-3">
                {entity.description}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Implementation note. */}
      <section>
        <h3 className="mb-4 text-lg font-semibold flex items-center gap-2">
          <NetworkIcon className="h-5 w-5 text-primary" />
          {t.knowledgeGraph.relationshipsHeader}
        </h3>
        <div className="space-y-2">
          {relationships.slice(0, 20).map((rel) => (
            <div
              key={rel.id}
              className="flex items-center gap-2 rounded-lg border p-3"
            >
              <span className="font-medium">{rel.source_name}</span>
              <Badge variant="outline">{rel.relationship_type}</Badge>
              <span className="font-medium">{rel.target_name}</span>
            </div>
          ))}
        </div>
      </section>
      </>
      )}
    </div>
  );
}
