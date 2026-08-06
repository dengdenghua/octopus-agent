import { useMemo } from "react";
import { BadgeCheckIcon, ClockIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  formatCount,
  type MarketItem,
} from "@/components/workspace/market/market-data";

/** 商品卡片：闲鱼式大图 + 价格 + 卖家。 */
export function MarketCard({
  item,
  onBuy,
  onOpen,
}: {
  item: MarketItem;
  onBuy: (item: MarketItem) => void;
  onOpen?: (item: MarketItem) => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen?.(item)}
      onKeyDown={(e) => {
        if (e.key === "Enter" && onOpen) onOpen(item);
      }}
      className="group relative flex cursor-pointer flex-col overflow-hidden rounded-xl bg-card transition hover:shadow-sm"
    >
      <div className="relative aspect-[3/4] w-full overflow-hidden bg-muted">
        <img
          src={item.cover}
          alt={item.title}
          loading="lazy"
          className="h-full w-full object-cover transition-transform duration-slow group-hover:scale-105"
        />
        {item.sold && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/55">
            <span className="rotate-[-12deg] rounded border-2 border-white/80 px-4 py-1 text-sm font-bold tracking-widest text-white">
              已售出
            </span>
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col px-2.5 pb-2.5 pt-2">
        <p className="line-clamp-2 text-[13px] font-medium leading-snug text-foreground">
          {item.title}
        </p>
        <div className="mt-auto flex items-end justify-between gap-2 pt-2">
          <span className="flex items-baseline gap-0.5 text-[15px] font-bold text-rose-500">
            {item.price}
            <span className="text-mini font-medium text-rose-400">积分</span>
          </span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onBuy(item);
            }}
            disabled={item.sold || item.mine}
            className={cn(
              "flex items-center gap-1 rounded-md px-2 py-1 text-mini font-semibold transition-colors",
              item.sold || item.mine
                ? "cursor-default bg-muted text-muted-foreground/60"
                : "bg-rose-500 text-white hover:bg-rose-600",
            )}
          >
            {item.mine ? "我的" : item.sold ? "已售" : "立即购买"}
          </button>
        </div>
        <div className="mt-1.5 flex items-center gap-1 text-mini text-muted-foreground">
          <span
            className="flex size-3.5 items-center justify-center rounded-full text-[9px] font-bold text-white"
            style={{ backgroundColor: item.sellerColor }}
          >
            {item.sellerInitial}
          </span>
          <span className="min-w-0 flex-1 truncate">{item.seller}</span>
        </div>
      </div>
    </div>
  );
}

/** 集市商品网格（响应式列数）。 */
export function MarketGrid({
  items,
  onBuy,
  onOpen,
}: {
  items: MarketItem[];
  onBuy: (item: MarketItem) => void;
  onOpen?: (item: MarketItem) => void;
}) {
  const cols = useMemo(() => {
    if (items.length >= 8) return "grid-cols-4";
    if (items.length >= 4) return "grid-cols-3";
    return "grid-cols-2 sm:grid-cols-3";
  }, [items.length]);

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-24 text-center">
        <BadgeCheckIcon className="size-8 text-muted-foreground/40" />
        <p className="text-sm text-muted-foreground">这个分类还没有商品</p>
        <p className="text-xs text-muted-foreground/60">
          去上架一件好物，赚点积分吧
        </p>
      </div>
    );
  }

  return (
    <div className={cn("grid gap-3", cols)}>
      {items.map((item) => (
        <MarketCard key={item.id} item={item} onBuy={onBuy} onOpen={onOpen} />
      ))}
    </div>
  );
}

/** 顶部余额条：当前社区积分 + 集市入口提示。 */
export function MarketBalanceBar({ balance }: { balance: number }) {
  return (
    <div className="flex items-center justify-between rounded-xl px-4 py-2.5 text-sm">
      <span className="flex items-center gap-2 text-muted-foreground">
        <ClockIcon className="size-4" />
        社区积分余额
      </span>
      <span className="text-base font-bold tabular-nums text-foreground">
        {formatCount(Math.max(0, balance))}
        <span className="ml-1 text-xs font-medium text-muted-foreground">
          积分
        </span>
      </span>
    </div>
  );
}