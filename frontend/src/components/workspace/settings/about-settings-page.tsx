
import { Suspense, lazy } from "react";

import { aboutMarkdown } from "./about-content";
import { BundleInfo } from "./bundle-info";

const LazyStreamdown = lazy(
  () => import("@/components/ai-elements/streamdown-host"),
);

export default function AboutSettingsPage() {
  return (
    <div>
      <Suspense
        fallback={
          <div className="whitespace-pre-wrap break-words">{aboutMarkdown}</div>
        }
      >
        <LazyStreamdown>{aboutMarkdown}</LazyStreamdown>
      </Suspense>
      <BundleInfo />
    </div>
  );
}
