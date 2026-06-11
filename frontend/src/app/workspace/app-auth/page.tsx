import { KeyRoundIcon, ShieldCheckIcon, LockIcon } from "lucide-react";

import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import AppAuthPage from "@/app/workspace/settings/app-auth-page";
import { useI18n } from "@/core/i18n/hooks";

export default function AppAuthRoutePage() {
  const { t } = useI18n();
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="mx-auto flex w-full max-w-(--container-width-md) flex-col gap-4 py-2">
          <section className="workspace-panel flex flex-col gap-4 rounded-[1.75rem] px-5 py-5 md:px-6">
            <div className="space-y-1">
              <div className="text-muted-foreground text-xs font-medium uppercase tracking-[0.18em]">
                {t.appAuthWrapperPage.securityKicker}
              </div>
              <div className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
                <KeyRoundIcon className="size-6 text-primary" />
                {t.appAuthWrapperPage.pageTitle}
              </div>
              <p className="text-muted-foreground max-w-2xl text-sm leading-6">
                {t.appAuthWrapperPage.pageSubtitle}
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="workspace-panel-subtle rounded-lg bg-gradient-to-br from-primary/5 to-transparent px-4 py-3 transition-all duration-200">
                <div className="mb-1 flex items-center gap-2 text-sm font-medium">
                  <div className="flex size-5 items-center justify-center rounded bg-primary/10">
                    <ShieldCheckIcon className="size-3 text-primary" />
                  </div>
                  {t.appAuthWrapperPage.feature1Title}
                </div>
                <p className="text-muted-foreground text-sm leading-6">
                  {t.appAuthWrapperPage.feature1Desc}
                </p>
              </div>
              <div className="workspace-panel-subtle rounded-lg bg-gradient-to-br from-blue-500/5 to-transparent px-4 py-3 transition-all duration-200">
                <div className="mb-1 flex items-center gap-2 text-sm font-medium">
                  <div className="flex size-5 items-center justify-center rounded bg-blue-500/10">
                    <LockIcon className="size-3 text-blue-500" />
                  </div>
                  {t.appAuthWrapperPage.feature2Title}
                </div>
                <p className="text-muted-foreground text-sm leading-6">
                  {t.appAuthWrapperPage.feature2Desc}
                </p>
              </div>
            </div>
          </section>
          <div className="workspace-panel rounded-[1.75rem] px-5 py-5 md:px-6">
            <AppAuthPage />
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
