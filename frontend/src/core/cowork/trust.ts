/**
 * 成员信任分（闲鱼式）— 前端只做展示与合并，评分全部在服务端完成。
 *
 * 服务端契约见 `runtime/memory/cowork/trust.py`：分数由显式权重从
 * 封签链保护的交付记录/接管历史算出，`components` 全量暴露保证可解释。
 */

export interface TrustComponents {
  completed: number;
  failed: number;
  rework_count: number;
  human_signed: number;
  takeover_count: number;
}

export interface TrustScore {
  member_id: string;
  kind: "agent" | "role" | "human";
  driver: "ai" | "human";
  accountable_owner: string;
  score: number;
  label: string;
  sample_size: number;
  components: TrustComponents;
}

export interface CoworkTrustResponse {
  thread_id: string;
  scores: TrustScore[];
  weights: Record<string, number>;
  basis: string;
}

/** 悬浮提示：这个分怎么来的，一句人话 + 构成明细。 */
export function trustTooltip(score: TrustScore): string {
  const c = score.components;
  if (score.sample_size === 0 && c.takeover_count === 0) {
    return "暂无交付记录，中立分。";
  }
  const parts = [
    `完成 ${c.completed} / 失败 ${c.failed}`,
    c.rework_count > 0 ? `返工 ${c.rework_count}` : null,
    c.human_signed > 0 ? `人工签收 ${c.human_signed}` : null,
    c.takeover_count > 0 ? `被接管 ${c.takeover_count}` : null,
  ].filter(Boolean);
  return `${parts.join(" · ")}（事件源带防篡改封签）`;
}

/** 分数 → 徽标配色。中国习惯：红=好？不——这是风险语义，沿用警示色阶。 */
export function trustBadgeClass(score: number): string {
  if (score >= 85) return "bg-emerald-500/10 text-emerald-600";
  if (score >= 70) return "bg-sky-500/10 text-sky-600";
  if (score >= 50) return "bg-amber-500/15 text-amber-700";
  return "bg-red-500/10 text-red-600";
}
