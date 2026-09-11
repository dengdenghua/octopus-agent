/** Purpose-specific diagrams, explicitly presented as illustrations, not generated results. */
export function TemplateCover({
  category,
  title,
}: {
  category: string;
  title: string;
}) {
  const storyboard = category === "漫剧短片";
  const product = category === "产品广告";
  const ui = category === "UI 动效";
  const music = category === "音乐视频";
  const accent = storyboard
    ? "#8062b6"
    : product
      ? "#ac7b42"
      : ui
        ? "#4b7caa"
        : music
          ? "#a05c7f"
          : "#4f8b80";
  const steps = storyboard
    ? ["角色设定", "连续分镜", "镜头制作"]
    : product
      ? ["产品卖点", "主视觉", "广告短片"]
      : ui
        ? ["界面结构", "交互路径", "动效演示"]
        : music
          ? ["音乐节拍", "视觉风格", "剪辑合成"]
          : ["视觉方向", "版式设计", "品牌表达"];
  return (
    <div
      className="relative h-full w-full bg-muted/35"
      aria-label={`${title} · 模板示意`}
      role="img"
    >
      <svg
        viewBox="0 0 360 144"
        className="h-full w-full"
        aria-hidden="true"
        style={{ color: accent }}
      >
        <rect
          x="0"
          y="0"
          width="360"
          height="144"
          fill="currentColor"
          opacity=".06"
        />
        {storyboard ? (
          [30, 135, 240].map((x, i) => (
            <g key={x}>
              <rect
                x={x}
                y="25"
                width="90"
                height="85"
                rx="5"
                fill="var(--background)"
                stroke="currentColor"
                strokeOpacity=".3"
              />
              <path
                d={`M${x + 6} 99 L${x + 30} ${68 + i * 5} L${x + 55} 90 L${x + 82} 55 V104 H${x + 6}Z`}
                fill="currentColor"
                opacity=".13"
              />
              <circle
                cx={x + 43 + i * 5}
                cy={54 + i * 2}
                r={12 - i * 2}
                fill="currentColor"
                opacity=".65"
              />
              <path
                d={`M${x + 26 + i * 6} 93 Q${x + 43 + i * 5} 52 ${x + 63} 93`}
                fill="currentColor"
                opacity=".65"
              />
              <text x={x + 8} y="39" fontSize="8" fill="currentColor">
                0{i + 1}
              </text>
            </g>
          ))
        ) : product ? (
          <g>
            <rect
              x="33"
              y="24"
              width="175"
              height="94"
              rx="5"
              fill="var(--background)"
            />
            <ellipse
              cx="122"
              cy="101"
              rx="49"
              ry="6"
              fill="currentColor"
              opacity=".13"
            />
            <rect
              x="89"
              y="44"
              width="65"
              height="51"
              rx="12"
              fill="currentColor"
              opacity=".75"
            />
            <circle
              cx="122"
              cy="66"
              r="14"
              fill="var(--background)"
              opacity=".7"
            />
            <circle cx="122" cy="66" r="8" fill="currentColor" />
            <rect
              x="224"
              y="24"
              width="101"
              height="43"
              rx="5"
              fill="var(--background)"
            />
            <path
              d="M236 39H308 M236 48H282"
              stroke="currentColor"
              strokeWidth="3"
              opacity=".4"
            />
            <rect
              x="224"
              y="76"
              width="101"
              height="42"
              rx="5"
              fill="currentColor"
              opacity=".15"
            />
            <path d="M266 86L283 97L266 108Z" fill="currentColor" />
          </g>
        ) : ui ? (
          <g>
            <rect
              x="36"
              y="22"
              width="225"
              height="97"
              rx="6"
              fill="var(--background)"
              stroke="currentColor"
              strokeOpacity=".3"
            />
            <path
              d="M36 40H261 M84 40V118"
              stroke="currentColor"
              opacity=".25"
            />
            <circle cx="48" cy="31" r="2" fill="currentColor" />
            <path
              d="M48 54H73 M48 66H68 M48 78H73"
              stroke="currentColor"
              strokeWidth="3"
              opacity=".3"
            />
            {[100, 149, 198].map((x) => (
              <rect
                key={x}
                x={x}
                y="54"
                width="37"
                height="47"
                rx="4"
                fill="currentColor"
                opacity=".15"
              />
            ))}
            <path d="M218 78L279 95L260 103L251 124Z" fill="currentColor" />
            <path
              d="M282 42H318 M302 33L319 42L302 51"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            />
          </g>
        ) : music ? (
          <g>
            <rect
              x="34"
              y="26"
              width="106"
              height="92"
              rx="5"
              fill="var(--background)"
            />
            <circle cx="87" cy="72" r="34" fill="currentColor" opacity=".65" />
            <circle cx="87" cy="72" r="11" fill="var(--background)" />
            {Array.from({ length: 19 }, (_, i) => (
              <rect
                key={i}
                x={160 + i * 8}
                y={67 - ((i * 13) % 28)}
                width="4"
                height={12 + ((i * 13) % 28) * 2}
                rx="2"
                fill="currentColor"
                opacity=".55"
              />
            ))}
            <path
              d="M158 111H312"
              stroke="currentColor"
              strokeWidth="3"
              opacity=".25"
            />
          </g>
        ) : (
          <g>
            <rect
              x="35"
              y="24"
              width="82"
              height="94"
              rx="4"
              fill="currentColor"
              opacity=".7"
            />
            <circle
              cx="76"
              cy="59"
              r="23"
              fill="var(--background)"
              opacity=".7"
            />
            <path
              d="M48 96H104 M48 104H88"
              stroke="var(--background)"
              strokeWidth="3"
            />
            <rect
              x="128"
              y="24"
              width="193"
              height="56"
              rx="4"
              fill="var(--background)"
            />
            <path
              d="M143 43H231 M143 58H204"
              stroke="currentColor"
              strokeWidth="5"
              opacity=".6"
            />
            {[128, 179, 230, 281].map((x, i) => (
              <rect
                key={x}
                x={x}
                y="91"
                width="40"
                height="27"
                rx="4"
                fill="currentColor"
                opacity={0.2 + i * 0.2}
              />
            ))}
          </g>
        )}
      </svg>
      <div
        className="absolute inset-x-3 bottom-1 flex justify-between text-[10px] text-muted-foreground"
        aria-hidden="true"
      >
        {steps.map((step) => (
          <span key={step}>{step}</span>
        ))}
      </div>
    </div>
  );
}
