import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { UploadedFileInfo } from "./api";
import type * as UploadsApiModule from "./api";
import { useAttachmentUploads } from "./use-attachment-uploads";

const uploadFilesWithProgressMock = vi.fn();

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<UploadsApiModule>();
  return {
    ...actual,
    uploadFilesWithProgress: (...args: unknown[]) =>
      uploadFilesWithProgressMock(...args),
  };
});

function uploaded(filename: string, marker: string): UploadedFileInfo {
  return {
    filename,
    size: marker.length,
    path: `/artifacts/${marker}/${filename}`,
    virtual_path: `uploads/${marker}/${filename}`,
    artifact_url: `https://example.test/${marker}/${filename}`,
    content_type: "image/png",
  };
}

function deferredUpload() {
  let resolve!: (value: { files: UploadedFileInfo[] }) => void;
  let progress: ((percent: number) => void) | undefined;
  const promise = new Promise<{ files: UploadedFileInfo[] }>((res) => {
    resolve = res;
  });
  return {
    promise,
    resolve,
    bindProgress: (callback: ((percent: number) => void) | undefined) => {
      progress = callback;
    },
    progress: (percent: number) => progress?.(percent),
  };
}

describe("useAttachmentUploads thread isolation", () => {
  beforeEach(() => {
    uploadFilesWithProgressMock.mockReset();
  });

  it("clears the ledger and ignores an old response for the same attachment key", async () => {
    const oldUpload = deferredUpload();
    const newUpload = deferredUpload();
    uploadFilesWithProgressMock
      .mockImplementationOnce(
        (
          _threadId: string,
          _files: File[],
          options?: { onProgress?: (percent: number) => void },
        ) => {
          oldUpload.bindProgress(options?.onProgress);
          return oldUpload.promise;
        },
      )
      .mockImplementationOnce(
        (
          _threadId: string,
          _files: File[],
          options?: { onProgress?: (percent: number) => void },
        ) => {
          newUpload.bindProgress(options?.onProgress);
          return newUpload.promise;
        },
      );

    const { result, rerender } = renderHook(
      ({ threadId }) => useAttachmentUploads(threadId),
      { initialProps: { threadId: "thread-a" } },
    );
    const oldFile = new File(["old"], "same.png", { type: "image/png" });
    const newFile = new File(["new"], "same.png", { type: "image/png" });

    act(() => result.current.start([{ key: "same-key", file: oldFile }]));
    expect(result.current.isUploading).toBe(true);

    rerender({ threadId: "thread-b" });
    expect(result.current.uploads.size).toBe(0);
    expect(result.current.isUploading).toBe(false);

    act(() => result.current.start([{ key: "same-key", file: newFile }]));
    expect(uploadFilesWithProgressMock).toHaveBeenNthCalledWith(
      2,
      "thread-b",
      [newFile],
      expect.any(Object),
    );

    act(() => oldUpload.progress(91));
    expect(result.current.uploads.get("same-key")?.progress).toBe(0);

    await act(async () => {
      oldUpload.resolve({ files: [uploaded("same.png", "old-thread")] });
      await oldUpload.promise;
    });
    expect(result.current.uploads.get("same-key")).toMatchObject({
      file: newFile,
      status: "uploading",
      progress: 0,
    });

    await act(async () => {
      newUpload.resolve({ files: [uploaded("same.png", "new-thread")] });
      await newUpload.promise;
    });
    await waitFor(() =>
      expect(result.current.uploads.get("same-key")).toMatchObject({
        file: newFile,
        status: "done",
        progress: 100,
        uploaded: { path: "/artifacts/new-thread/same.png" },
      }),
    );
  });
});
