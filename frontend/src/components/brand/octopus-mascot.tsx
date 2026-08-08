"use client";

import { cn } from "@/lib/utils";
import { useMemo } from "react";

type MascotMood = "idle" | "thinking" | "happy" | "working";

interface OctopusMascotProps {
  mood?: MascotMood;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const sizeMap = { sm: 120, md: 150, lg: 180 };

export function OctopusMascot({
  mood = "idle",
  size = "sm",
  className,
}: OctopusMascotProps) {
  const dim = sizeMap[size];

  const animDuration = useMemo(() => {
    if (mood === "working") return 0.6;
    if (mood === "thinking") return 1.4;
    if (mood === "happy") return 0.5;
    return 2.5;
  }, [mood]);

  return (
    <div
      className={cn("relative select-none pointer-events-none", className)}
      style={{ width: dim, height: dim }}
    >
      <style>{`
        @keyframes om-float {
          0%, 100% { transform: translate(0, 0) rotate(-2deg); }
          50%      { transform: translate(0, -3px) rotate(2deg); }
        }
        @keyframes om-happy {
          0%, 100% { transform: translate(0, 0) rotate(-3deg) scale(1); }
          25%      { transform: translate(0, -10px) rotate(3deg) scale(1.04); }
          50%      { transform: translate(0, -6px) rotate(-1deg) scale(0.98); }
          75%      { transform: translate(0, -12px) rotate(2deg) scale(1.02); }
        }
        @keyframes om-think {
          0%, 100% { transform: translate(0, 0) rotate(-1deg); }
          50%      { transform: translate(-2px, -2px) rotate(1deg); }
        }
        @keyframes om-working {
          0%, 100% { transform: translate(0, 0) rotate(-2deg); }
          25%      { transform: translate(1px, -2px) rotate(2deg); }
          75%      { transform: translate(-1px, -1px) rotate(-1deg); }
        }
        @keyframes om-dot {
          0%, 80%, 100% { opacity: 0.2; transform: translate(0, 0) scale(0.5); }
          40%           { opacity: 1; transform: translate(0, -5px) scale(1); }
        }
        @keyframes om-sparkle {
          0%, 100% { opacity: 0; transform: scale(0.3) rotate(0deg); }
          50%      { opacity: 0.9; transform: scale(1) rotate(180deg); }
        }

        .om-img-wrap {
          width: 100%;
          height: 100%;
          animation: om-float ${animDuration}s ease-in-out infinite;
        }
        .om-img-wrap.happy { animation: om-happy 0.8s cubic-bezier(0.34, 1.56, 0.64, 1) infinite; }
        .om-img-wrap.thinking { animation: om-think 1.8s ease-in-out infinite; }
        .om-img-wrap.working { animation: om-working 0.7s ease-in-out infinite; }

        .om-img {
          width: 100%;
          height: 100%;
          object-fit: contain;
          display: block;
        }

        .om-dot { animation: om-dot 1s ease-in-out infinite; }
        .om-dot:nth-child(2) { animation-delay: 0.15s; }
        .om-dot:nth-child(3) { animation-delay: 0.3s; }

        .om-sparkle { animation: om-sparkle 1.3s ease-in-out infinite; }
        .om-sparkle.s2 { animation-delay: 0.4s; }
      `}</style>

      {/* Mood indicators */}
      {mood === "thinking" && (
        <div className="absolute z-10 flex gap-1" style={{ top: "12%", left: "20%" }}>
          <div className="om-dot h-2 w-2 rounded-full" style={{ background: "var(--primary)" }} />
          <div className="om-dot h-2 w-2 rounded-full" style={{ background: "var(--primary)" }} />
          <div className="om-dot h-2 w-2 rounded-full" style={{ background: "var(--primary)" }} />
        </div>
      )}
      {mood === "working" && (
        <>
          <div
            className="om-sparkle absolute z-10"
            style={{ top: "5%", left: "15%", fontSize: dim * 0.1, color: "var(--primary)", opacity: 0.8 }}
          >
            ✦
          </div>
          <div
            className="om-sparkle s2 absolute z-10"
            style={{ top: "18%", left: "8%", fontSize: dim * 0.08, color: "var(--primary)", opacity: 0.6 }}
          >
            ✧
          </div>
        </>
      )}

      <div className={cn("om-img-wrap", mood)}>
        <img
          src="/images/octopus-mascot-new.png"
          alt="Octopus assistant"
          draggable={false}
          className="om-img"
        />
      </div>
    </div>
  );
}
