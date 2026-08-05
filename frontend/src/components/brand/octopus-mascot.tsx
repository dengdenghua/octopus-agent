import { cn } from "@/lib/utils";

type MascotMood = "idle" | "thinking" | "happy" | "working";

interface OctopusMascotProps {
  mood?: MascotMood;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const sizeMap = {
  sm: 90,
  md: 115,
  lg: 145,
};

export function OctopusMascot({
  mood = "idle",
  size = "sm",
  className,
}: OctopusMascotProps) {
  const dim = sizeMap[size];

  return (
    <div
      className={cn("relative select-none", className)}
      style={{ width: dim, height: dim }}
    >
      <style>{`
        @keyframes octo-float {
          0%, 100% { transform: translate(0,0) rotate(0deg); }
          50% { transform: translate(1px,-2px) rotate(-2deg); }
        }
        @keyframes octo-thinking-dot {
          0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
          40% { opacity: 1; transform: scale(1); }
        }
        .octo-mascot-img {
          animation: octo-float 3.5s ease-in-out infinite;
          transform-origin: 90% 40%;
        }
        .thinking-dot { animation: octo-thinking-dot 1.4s ease-in-out infinite; }
        .thinking-dot:nth-child(2) { animation-delay: 0.2s; }
        .thinking-dot:nth-child(3) { animation-delay: 0.4s; }
      `}</style>

      {mood === "thinking" && (
        <div className="absolute top-2 right-14 flex gap-0.5 z-10">
          <div className="thinking-dot h-1.5 w-1.5 rounded-full bg-primary/80" />
          <div className="thinking-dot h-1.5 w-1.5 rounded-full bg-primary/80" />
          <div className="thinking-dot h-1.5 w-1.5 rounded-full bg-primary/80" />
        </div>
      )}

      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/images/octopus-mascot-final.jpg"
        alt=""
        width={dim}
        height={dim}
        className="octo-mascot-img block"
        style={{
          width: dim,
          height: dim,
          objectFit: "contain",
          objectPosition: "right top",
          mixBlendMode: "multiply",
        }}
      />
    </div>
  );
}
