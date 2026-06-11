/**
 * Backward-compatible re-export from the new mention-autocomplete module.
 *
 * The original file-mention.tsx has been superseded by
 * mention-autocomplete.tsx which supports all mention types (@file,
 * @symbol, @docs, @web, @git, @folder, @terminal).
 *
 * Existing consumers that import from this file continue to work
 * with no changes required.
 */

export { useFileMention } from "./mention-autocomplete";
export { MentionAutocompletePopup as FileMentionPopup } from "./mention-autocomplete";

// Re-export the old FileEntry type shape for type compatibility
export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "dir";
  language?: string;
}
