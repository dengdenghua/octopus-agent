type AvatarProps = { id: string; name: string; team?: boolean; className?: string };

// Integer pixel coordinates and stable IDs keep every portrait crisp and consistent.
export function PixelAgentAvatar({ id, name, team = false, className = "size-8" }: AvatarProps) {
  let seed = Array.from(id).reduce((hash, char) => Math.imul(hash ^ char.charCodeAt(0), 16777619) >>> 0, 2166136261);
  seed = Math.imul(seed ^ (seed >>> 16), 2246822507) >>> 0;
  seed = (seed ^ (seed >>> 13)) >>> 0;
  const engineering = /工程|研发|开发|机械|结构|硬件|制造|测试/.test(name);
  const science = /科研|研究|科学|实验|生物|化学|物理|医学/.test(name);
  const education = /教育|教师|教学|导师|学习|教练/.test(name);
  const business = /金融|财务|投资|股票|会计|法务|经营|商务/.test(name);
  const accent = `hsl(${seed % 360} 32% ${38 + ((seed >>> 9) % 16)}%)`;
  const trim = `hsl(${(seed % 360 + 55) % 360} 48% 72%)`;
  const skin = ["#f4cdaa", "#dca77f", "#bd805e", "#e8bda5", "#996448"][(seed >>> 5) % 5]!;
  const hair = ["#363346", "#5b403c", "#725447", "#454b58", "#a08e7a", "#ac754d"][(seed >>> 12) % 6]!;
  const hairstyle = (seed >>> 17) % 5;
  const accessory = (seed >>> 21) % 4;
  const uniform = (seed >>> 25) % 4;
  const portrait = (offset: number, color: string) => <g transform={`translate(${offset} 0)`}>
    <path d="M4 11h6v1h2v4H2v-4h2z" fill={color} />
    <path d="M6 10h2v3H6z" fill={skin} />
    <path d="M4 3h6v1h1v5h-1v2H4V9H3V4h1z" fill={hair} />
    <path d="M4 5h6v4H9v2H5V9H4z" fill={skin} />
    <path d={[
      "M4 3h6v2H4zM4 5h2v1H4z",
      "M3 3h7v1H3zM3 4h3v2H3zM3 6h1v5H3z",
      "M5 2h4v1H5zM4 3h6v1H4z",
      "M4 3h6v1H4zM4 4h1v2H4zM9 4h1v2H9z",
      "M3 3h8v2H3zM2 5h2v7H2zM10 5h2v7h-2z",
    ][hairstyle]} fill={hair} />
    <path d="M5 6h1v1H5zm3 0h1v1H8z" fill="#302e3a" />
    <path d="M6 9h2v1H6z" fill="#ac6b61" />
    {engineering && accessory === 0 ? <><path d="M3 3h1V2h6v1h1v2H3z" fill={trim} /><path d="M6 2h2v3H6z" fill={accent} /></> : accessory === 1 ? <path d="M2 5h1v4H2zM11 5h1v5h-2V9h1z" fill={accent} /> : (science || education || accessory === 2) ? <path d="M4 6h3v2H4zm4 0h3v2H8zM7 6h1" fill="none" stroke="#464753" strokeWidth="0.5" /> : null}
    <path d={["M3 14h8v1H3z", "M4 12h1v4H4zM9 12h1v4H9z", "M5 12h1v1H5zM8 12h1v1H8z", "M3 12h2v2H3zM9 12h2v2H9z"][uniform]} fill={trim} />
    {science ? <path d="M4 12h2l1 2 1-2h2v4H4z" fill="#e9ede7" /> : business ? <path d="M6 12h2l-1 1 1 3H6l1-3z" fill="#e9dfce" /> : education ? <><path d="M8 13h4v3H8z" fill="#e7c990" /><path d="M9 13h1v3H9z" fill="#f6e4bc" /></> : <path d="M4 13h2v1H4z" fill="#e9dfce" />}
    <rect x={8 + ((seed >>> 3) % 2)} y="14" width="1" height="1" fill={trim} />
  </g>;
  return <svg aria-hidden="true" focusable="false" viewBox={team ? "0 0 22 18" : "0 0 16 18"} className={`${className} shrink-0`} shapeRendering="crispEdges">
    {team ? <><g opacity="0.8" transform="translate(7 -1)">{portrait(0, "#8b9f94")}</g>{portrait(0, accent)}</> : portrait(1, accent)}
  </svg>;
}
