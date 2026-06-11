export interface AlertRule {
  name: string;
  metric: string;
  condition: ">" | "<" | "==" | ">=" | "<=";
  threshold: number;
  duration: number;
  severity: "info" | "warning" | "critical";
  message_template?: string;
}

export interface ActiveAlert {
  rule_name: string;
  severity: "info" | "warning" | "critical";
  message: string;
  value: number;
  timestamp: number;
}

export interface TraceSummary {
  trace_id: string;
  span_count: number;
  first_seen: number;
}

export interface Span {
  span_id: string;
  parent_span_id?: string;
  name: string;
  start_time: number;
  end_time?: number;
  duration_ms?: number;
  attributes?: Record<string, unknown>;
}

export interface MetricsSummary {
  metrics: Record<string, unknown>;
  health: Record<string, unknown>;
  alerts: ActiveAlert[];
}

export interface TelemetryStats {
  enabled: boolean;
  metrics_exporter: string;
  logs_exporter: string;
  traces_exporter: string;
  redact_prompts: boolean;
  redact_tool_content: boolean;
}
