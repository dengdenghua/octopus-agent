import { UnifiedStore } from "@/components/store/unified-store";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";

export default function StorePage() {
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="p-0">
        <UnifiedStore />
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
