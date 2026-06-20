import {
  ChevronDownIcon,
  FolderIcon,
  MoreHorizontal,
  PlusIcon,
  SparklesIcon,
  Trash2,
} from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { useState, useEffect } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { useDeleteProject, useProjects } from "@/core/projects/hooks";
import { useFeatureSeen } from "@/hooks/use-feature-seen";

import { CreateProjectDialog } from "./create-project-dialog";

function ProjectCollapsible({
  projects,
  onCreateClick,
  onDeleteProject,
  t,
}: {
  projects: Array<{ id: string; name: string; icon?: string }>;
  onCreateClick: () => void;
  onDeleteProject: (id: string) => void;
  t: { common: { delete: string }; sidebar: { projects: string } };
}) {
  return (
    <Collapsible defaultOpen className="group/projects">
      <SidebarGroup className="pt-0">
        <SidebarGroupLabel className="flex h-6 items-center justify-between px-1.5 text-[11px]">
          <CollapsibleTrigger className="flex items-center gap-1">
            <ChevronDownIcon className="size-3 transition-transform group-data-[state=closed]/projects:-rotate-90" />
            <span>{t.sidebar.projects}</span>
          </CollapsibleTrigger>
          <button
            onClick={onCreateClick}
            className="text-muted-foreground hover:text-foreground transition-colors"
            title={`${t.sidebar.projects}+`}
          >
            <PlusIcon className="size-4" />
          </button>
        </SidebarGroupLabel>
        <CollapsibleContent>
          <SidebarMenu>
            {projects.map((project) => (
              <SidebarMenuItem
                key={project.id}
                className="group-data-[collapsible=icon]:px-0 px-1.5"
              >
                <SidebarMenuButton asChild>
                  <Link
                    className="text-muted-foreground text-[13px]"
                    to="/workspace/realtime/new"
                  >
                    <FolderIcon className="size-4" />
                    <span>
                      {project.icon} {project.name}
                    </span>
                  </Link>
                </SidebarMenuButton>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <SidebarMenuAction>
                      <MoreHorizontal className="size-4" />
                    </SidebarMenuAction>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" side="right">
                    <DropdownMenuItem
                      className="text-destructive"
                      onClick={() => onDeleteProject(project.id)}
                    >
                      <Trash2 className="mr-2 size-4" />
                      {t.common.delete}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </CollapsibleContent>
      </SidebarGroup>
    </Collapsible>
  );
}

export function WorkspaceNavChatList({
  showProjects = true,
  showOnlyProjects = false,
}: {
  showProjects?: boolean;
  showOnlyProjects?: boolean;
}) {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const { data: projects = [] } = useProjects();
  const { mutate: deleteProject } = useDeleteProject();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const skillsSeen = useFeatureSeen(
    "skills",
    pathname.startsWith("/workspace/skills"),
  );

  useEffect(() => {
    setMounted(true);
  }, []);

  // Only render projects section
  if (showOnlyProjects) {
    return (
      <>
        {mounted && (
          <ProjectCollapsible
            projects={projects}
            onCreateClick={() => setCreateDialogOpen(true)}
            onDeleteProject={(id) => deleteProject(id)}
            t={t}
          />
        )}
        <CreateProjectDialog
          open={createDialogOpen}
          onOpenChange={setCreateDialogOpen}
        />
      </>
    );
  }

  return (
    <>
      <SidebarGroup className="pt-0">
        <SidebarMenu>
          <SidebarMenuItem className="group-data-[collapsible=icon]:px-0 px-1.5 mt-0">
            <SidebarMenuButton
              isActive={pathname.startsWith("/workspace/skills")}
              asChild
              className="text-muted-foreground rounded-lg py-1 text-[13px] transition-all duration-150 hover:bg-muted hover:text-foreground data-[active=true]:bg-muted data-[active=true]:text-foreground data-[active=true]:font-medium"
            >
              <Link to="/workspace/skills">
                <SparklesIcon className="size-[15px]" />
                <span className="flex items-center gap-1.5">
                  {t.sidebar.skills}
                  {!skillsSeen && (
                    <span className="rounded bg-primary/10 px-1 py-0.5 text-[9px] font-medium leading-none text-primary">
                      NEW
                    </span>
                  )}
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarGroup>

      {/* Projects below nav links when showProjects is true */}
      {showProjects && mounted && (
        <ProjectCollapsible
          projects={projects}
          onCreateClick={() => setCreateDialogOpen(true)}
          onDeleteProject={(id) => deleteProject(id)}
          t={t}
        />
      )}

      <CreateProjectDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
      />
    </>
  );
}
