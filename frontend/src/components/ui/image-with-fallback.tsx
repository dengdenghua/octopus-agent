import { useState, type ComponentProps } from "react";

export function ImageWithFallback({
  src,
  alt = "",
  className,
  onError,
  ...props
}: ComponentProps<"img">) {
  const [failedSrc, setFailedSrc] = useState<ComponentProps<"img">["src"]>();
  if (!src || failedSrc === src) {
    return (
      <span
        role="img"
        aria-label={alt ? `${alt}（图片暂不可用）` : "图片暂不可用"}
        className={`${className ?? ""} inline-flex items-center justify-center bg-muted text-xs text-muted-foreground`}
      >
        图片暂不可用
      </span>
    );
  }
  return (
    <img
      {...props}
      src={src}
      alt={alt}
      className={className}
      onError={(event) => {
        setFailedSrc(src);
        onError?.(event);
      }}
    />
  );
}
