/**
 * API functions for file uploads
 */

import type { components } from "@/core/api/openapi-types";

import { getBackendBaseURL } from "../config";
import { authHeaders } from "@/core/auth/api";

// Generated from the backend's ``UploadFileMetadata`` pydantic model
// (see runtime/sensing/siphon/uploads_router.py). Drift is blocked
// by the ``openapi-contract`` CI job · ADR-004.
//
// Note · this drop of the ``markdown_*`` quadruplet (markdown_file /
// markdown_path / markdown_virtual_path / markdown_artifact_url)
// that used to live on the hand-written interface · a grep of the
// frontend at the time of this replacement showed them declared but
// NEVER read. If a future feature needs markdown-companion fields,
// add them to the backend pydantic model · they flow through here
// automatically.
export type UploadedFileInfo = components["schemas"]["UploadFileMetadata"];
export type UploadResponse = components["schemas"]["UploadPostResponse"];
export type ListFilesResponse = components["schemas"]["UploadsListResponse"];

async function readErrorDetail(
  response: Response,
  fallback: string,
): Promise<string> {
  const error = await response.json().catch(() => ({ detail: fallback }));
  return error.detail ?? fallback;
}

/**
 * Upload files to a thread
 */
export async function uploadFiles(
  threadId: string,
  files: File[],
): Promise<UploadResponse> {
  const formData = new FormData();

  files.forEach((file) => {
    formData.append("files", file);
  });

  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/uploads`,
    {
      method: "POST",
      headers: authHeaders(),
      body: formData,
    },
  );

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "Upload failed"));
  }

  return response.json();
}

/**
 * List all uploaded files for a thread
 */
export async function listUploadedFiles(
  threadId: string,
): Promise<ListFilesResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/uploads/list`,
    { headers: authHeaders() },
  );

  if (!response.ok) {
    throw new Error(
      await readErrorDetail(response, "Failed to list uploaded files"),
    );
  }

  return response.json();
}

/**
 * Delete an uploaded file
 */
export async function deleteUploadedFile(
  threadId: string,
  filename: string,
): Promise<{ success: boolean; message: string }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/uploads/${encodeURIComponent(filename)}`,
    {
      method: "DELETE",
      headers: authHeaders(),
    },
  );

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "Failed to delete file"));
  }

  return response.json();
}
