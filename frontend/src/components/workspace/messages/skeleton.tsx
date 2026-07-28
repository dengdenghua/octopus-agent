import { Skeleton } from "@/components/ui/skeleton";

function SkeletonBar({
  className,
  originRight,
}: {
  className?: string;
  originRight?: boolean;
}) {
  return (
    <div
      className={`animate-skeleton-entrance fill-mode-[forwards] overflow-hidden rounded-lg opacity-0 ${originRight ? "origin-[right]" : "origin-[left]"} ${className ?? ""}`}
    >
      <Skeleton className="h-full w-full rounded-lg" />
    </div>
  );
}

export function MessageListSkeleton() {
  return (
    <div className="flex w-full max-w-(--container-width-md) flex-col gap-12 p-8 pt-16">
      <div
        role="human-message"
        className="flex w-[50%] flex-col items-end gap-2 self-end"
      >
        <SkeletonBar
          className="h-6 w-full [animation-delay:0ms]"
          originRight
        />
        <SkeletonBar
          className="h-6 w-[80%] [animation-delay:60ms]"
          originRight
        />
      </div>
      <div role="assistant-message" className="flex flex-col gap-2">
        <SkeletonBar className="h-6 w-full [animation-delay:120ms]" />
        <SkeletonBar className="h-6 w-full [animation-delay:180ms]" />
        <SkeletonBar className="h-6 w-[70%] [animation-delay:240ms]" />
        <SkeletonBar className="h-6 w-full [animation-delay:300ms]" />
        <SkeletonBar className="h-6 w-full [animation-delay:360ms]" />
        <SkeletonBar className="h-6 w-full [animation-delay:420ms]" />
        <SkeletonBar className="h-6 w-[60%] [animation-delay:480ms]" />
        <SkeletonBar className="h-6 w-[40%] [animation-delay:540ms]" />
      </div>
    </div>
  );
}
