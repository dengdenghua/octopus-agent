import { Github as GitHubLogoIcon } from "lucide-react";
import { useMemo } from "react";

import { GITHUB_URL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";

export function Footer() {
  const { t } = useI18n();
  const year = useMemo(() => new Date().getFullYear(), []);

  const links = useMemo(
    () => [
      {
        title: t.landingFooter.productTitle,
        items: [
          { label: t.landingFooter.workspaceLink, href: "/workspace" },
          { label: t.landingFooter.aboutLink, href: "/about" },
        ],
      },
      {
        title: t.landingFooter.resourcesTitle,
        items: [
          { label: "GitHub", href: GITHUB_URL },
          {
            label: t.landingFooter.skillMarketLink,
            href: "/workspace/agents?surface=chat&tab=skills",
          },
        ],
      },
      {
        title: t.landingFooter.communityTitle,
        items: [
          { label: "Discord", href: "#" },
          { label: t.landingFooter.wechat, href: "#" },
        ],
      },
    ],
    [t],
  );

  return (
    <footer className="container-md mx-auto mt-32">
      <hr className="from-border/0 to-border/0 m-0 h-px w-full border-none bg-linear-to-r via-white/20" />

      <div className="grid grid-cols-2 gap-8 py-12 md:grid-cols-4">
        <div className="col-span-2 md:col-span-1">
          <div className="flex items-center gap-2 mb-3">
            <div className="flex size-6 items-center justify-center border border-white/12 bg-white/[0.04] text-white/80">
              <svg width="10" height="10" viewBox="0 0 512 512" fill="none">
                <path
                  d="M256 32C167.6 32 96 103.6 96 192c0 52.8 25.6 99.6 65.2 128.8C128 348 96 404 96 448c0 17.7 14.3 32 32 32s32-14.3 32-32c0-28 16-68 40-96 8 4 16.4 7.2 25.2 9.6-4 26.4-9.2 56-9.2 86.4 0 17.7 14.3 32 32 32s32-14.3 32-32c0-26.4 4-52 8-76 12-2.4 23.6-6 34.8-11.2C348 384 368 420 368 448c0 17.7 14.3 32 32 32s32-14.3 32-32c0-48-36-108-72-147.2C399.6 271.6 416 233.6 416 192c0-88.4-71.6-160-160-160zm0 64c53 0 96 43 96 96s-43 96-96 96-96-43-96-96 43-96 96-96z"
                  fill="currentColor"
                />
              </svg>
            </div>
            <span className="text-lg font-bold text-white/80">Octopus</span>
          </div>
          <p className="text-xs leading-relaxed text-white/40">
            {t.landingFooter.tagline}
          </p>
        </div>

        {links.map((group) => (
          <div key={group.title}>
            <h3 className="mb-3 text-sm font-semibold text-white/70">
              {group.title}
            </h3>
            <ul className="space-y-2">
              {group.items.map((item) => (
                <li key={item.label}>
                  <a
                    href={item.href}
                    className="text-sm text-white/40 transition-colors hover:text-white/70"
                  >
                    {item.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="flex flex-col items-center justify-center gap-3 border-t border-white/[0.06] py-6">
        <div className="flex items-center gap-3">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-white/30 transition-colors hover:text-white/60"
          >
            <GitHubLogoIcon className="size-4" />
          </a>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-white/30">
          <span>&copy; {year}</span>
          <span className="font-semibold text-white/45">Octopus</span>
          <span>· MIT License</span>
        </div>
      </div>
    </footer>
  );
}
