import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchCommunityFeed,
  mergeComments,
  type CommunityPost,
} from "./community-data";

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("community data provenance", () => {
  it("does not manufacture activity for an empty community", async () => {
    expect(await fetchCommunityFeed()).toEqual({
      posts: [],
      total: 0,
      hasMore: false,
    });
    expect(mergeComments({ id: "empty" } as CommunityPost)).toEqual([]);
  });
  it("keeps a successful empty remote response empty instead of reviving cached posts", async () => {
    localStorage.setItem("octopus.squareBaseUrl", "https://community.example");
    localStorage.setItem(
      "octopus.community.feed.v1",
      JSON.stringify({
        posts: [{ id: "old", title: "Old cached post", author: "Someone" }],
      }),
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({ posts: [] }) })),
    );
    expect((await fetchCommunityFeed()).posts).toEqual([]);
  });
  it("preserves explicit comments and comments written by the user", () => {
    const original = { id: "real", createdAt: 1, content: "Existing" };
    const own = { id: "mine", createdAt: 2, content: "Mine" };
    localStorage.setItem(
      "octopus.community.user-comments.v1",
      JSON.stringify({ post: [own] }),
    );
    expect(
      mergeComments({ id: "post", comments: [original] } as CommunityPost).map(
        (x) => x.id,
      ),
    ).toEqual(["mine", "real"]);
  });
});
