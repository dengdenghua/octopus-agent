/**
 * Composer attachment uploads: start on attach, not on send.
 *
 * The composer used to hand raw ``File`` objects to the send path, which
 * uploaded them *after* the user hit send. That made a real progress bar
 * impossible (nothing was in flight yet) and pushed the completion signal into
 * a detached toast. This hook moves the upload to attach time so the chip
 * itself can show progress and the send button can wait for it.
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { uploadFilesWithProgress, type UploadedFileInfo } from "./api";

export type AttachmentUploadStatus = "uploading" | "done" | "error";

export interface AttachmentUpload {
  /** Stable key shared with the composer chip (see ``uploadFileKey``). */
  key: string;
  file: File;
  status: AttachmentUploadStatus;
  /** 0–100. Reaches 100 only once the server response is parsed. */
  progress: number;
  uploaded?: UploadedFileInfo;
  error?: string;
}

export interface AttachmentUploadsApi {
  uploads: Map<string, AttachmentUpload>;
  /** True while any attachment is still in flight. */
  isUploading: boolean;
  /** True when at least one attachment failed and is still attached. */
  hasFailed: boolean;
  start: (entries: { key: string; file: File }[]) => void;
  retry: (key: string) => void;
  remove: (key: string) => void;
  reset: () => void;
  /** Server metadata for every attachment that finished uploading. */
  completed: () => UploadedFileInfo[];
}

interface AttachmentUploadState {
  threadId: string | undefined | null;
  uploads: Map<string, AttachmentUpload>;
}

const EMPTY_UPLOADS = new Map<string, AttachmentUpload>();

/**
 * ``threadId`` may be a client-minted UUID for a thread the server has never
 * seen. That is fine: the upload endpoint runs with ``allow_create=True`` and
 * materializes the thread. The trade-off is deliberate — attaching a file to a
 * brand-new conversation creates it server-side even if the user never sends.
 */
export function useAttachmentUploads(
  threadId: string | undefined | null,
): AttachmentUploadsApi {
  const [state, setState] = useState<AttachmentUploadState>(() => ({
    threadId,
    uploads: new Map(),
  }));
  // Files are kept out of state-dependency chains so ``retry`` never needs a
  // fresh closure over the map.
  const filesRef = useRef<Map<string, File>>(new Map());
  const attemptsRef = useRef<Map<string, symbol>>(new Map());
  const generationRef = useRef(0);
  const threadIdRef = useRef(threadId);
  useLayoutEffect(() => {
    if (Object.is(threadIdRef.current, threadId)) return;
    threadIdRef.current = threadId;
    generationRef.current += 1;
    filesRef.current.clear();
    attemptsRef.current.clear();
  }, [threadId]);
  const disposedRef = useRef(false);

  // Never expose the previous thread's ledger for even the render before the
  // reset effect commits. This also keeps a still-pending old upload from
  // blocking the new thread's send button.
  const uploads = Object.is(state.threadId, threadId)
    ? state.uploads
    : EMPTY_UPLOADS;

  useEffect(() => {
    const attempts = attemptsRef.current;
    const files = filesRef.current;
    disposedRef.current = false;
    return () => {
      disposedRef.current = true;
      generationRef.current += 1;
      attempts.clear();
      files.clear();
    };
  }, []);

  useLayoutEffect(() => {
    setState((current) => {
      // A caller may start a new-thread upload from a layout effect before
      // this layout reset runs. In that case `start` has already moved the
      // state owner to this thread, so preserve its fresh ledger.
      if (Object.is(current.threadId, threadId)) return current;
      return { threadId, uploads: new Map() };
    });
  }, [threadId]);

  const run = useCallback((key: string, file: File) => {
    const tid = threadIdRef.current;
    const generation = generationRef.current;
    const attempt = Symbol(key);
    attemptsRef.current.set(key, attempt);
    const patch = (changes: Partial<AttachmentUpload>) => {
      if (
        disposedRef.current ||
        generationRef.current !== generation ||
        !Object.is(threadIdRef.current, tid) ||
        attemptsRef.current.get(key) !== attempt
      ) {
        return;
      }
      setState((current) => {
        if (!Object.is(current.threadId, tid)) return current;
        const existing = current.uploads.get(key);
        if (!existing) return current;
        const uploads = new Map(current.uploads);
        uploads.set(key, { ...existing, ...changes });
        return { ...current, uploads };
      });
    };
    if (!tid) {
      patch({
        status: "error",
        error: "No conversation to upload into",
      });
      return;
    }
    void uploadFilesWithProgress(tid, [file], {
      onProgress: (percent) => patch({ progress: percent }),
    })
      .then((response) => {
        const uploaded = response.files?.[0];
        if (!uploaded) {
          patch({
            status: "error",
            error: "Upload returned no file metadata",
          });
          return;
        }
        patch({ status: "done", progress: 100, uploaded });
      })
      .catch((error: unknown) => {
        patch({
          status: "error",
          error: error instanceof Error ? error.message : "Upload failed",
        });
      });
  }, []);

  const start = useCallback(
    (entries: { key: string; file: File }[]) => {
      if (entries.length === 0) return;
      const fresh = entries.filter(({ key }) => !filesRef.current.has(key));
      if (fresh.length === 0) return;
      for (const { key, file } of fresh) filesRef.current.set(key, file);
      const tid = threadIdRef.current;
      setState((current) => {
        const next = Object.is(current.threadId, tid)
          ? new Map(current.uploads)
          : new Map<string, AttachmentUpload>();
        for (const { key, file } of fresh) {
          next.set(key, { key, file, status: "uploading", progress: 0 });
        }
        return { threadId: tid, uploads: next };
      });
      // Parallel is fine here: the composer caps attachment count and each
      // upload is a single small request.
      for (const { key, file } of fresh) run(key, file);
    },
    [run],
  );

  const retry = useCallback(
    (key: string) => {
      const file = filesRef.current.get(key);
      if (!file) return;
      const tid = threadIdRef.current;
      setState((current) => {
        if (!Object.is(current.threadId, tid)) return current;
        const existing = current.uploads.get(key);
        if (!existing) return current;
        const uploads = new Map(current.uploads);
        uploads.set(key, {
          ...existing,
          status: "uploading",
          progress: 0,
          error: undefined,
        });
        return { ...current, uploads };
      });
      run(key, file);
    },
    [run],
  );

  const remove = useCallback((key: string) => {
    filesRef.current.delete(key);
    attemptsRef.current.delete(key);
    const tid = threadIdRef.current;
    setState((current) => {
      if (!Object.is(current.threadId, tid) || !current.uploads.has(key)) {
        return current;
      }
      const next = new Map(current.uploads);
      next.delete(key);
      return { ...current, uploads: next };
    });
  }, []);

  const reset = useCallback(() => {
    generationRef.current += 1;
    filesRef.current.clear();
    attemptsRef.current.clear();
    const tid = threadIdRef.current;
    setState((current) =>
      Object.is(current.threadId, tid) && current.uploads.size === 0
        ? current
        : { threadId: tid, uploads: new Map() },
    );
  }, []);

  const completed = useCallback(() => {
    const out: UploadedFileInfo[] = [];
    for (const entry of uploads.values()) {
      if (entry.status === "done" && entry.uploaded) out.push(entry.uploaded);
    }
    return out;
  }, [uploads]);

  let isUploading = false;
  let hasFailed = false;
  for (const entry of uploads.values()) {
    if (entry.status === "uploading") isUploading = true;
    else if (entry.status === "error") hasFailed = true;
  }

  // Consumers list this object in `useCallback` deps (the composer's submit
  // and attach handlers). Without a memo it would be a new identity on every
  // render and rebuild those callbacks each keystroke.
  return useMemo(
    () => ({
      uploads,
      isUploading,
      hasFailed,
      start,
      retry,
      remove,
      reset,
      completed,
    }),
    [uploads, isUploading, hasFailed, start, retry, remove, reset, completed],
  );
}
