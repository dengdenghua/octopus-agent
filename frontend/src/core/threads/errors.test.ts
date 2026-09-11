import { describe, expect, it } from "vitest";

import { getStreamErrorMessage, publicExecutionErrorMessage } from "./errors";

it("renders nested historical tool-catalog failures without transport JSON", () => {
  const wrapped = JSON.stringify({
    codexErrorInfo: "other",
    message: JSON.stringify({
      error: { message: "Responses tool catalog is too large" },
    }),
  });
  expect(publicExecutionErrorMessage(wrapped)).toBe(
    "当前任务加载的工具过多，已超过执行接口上限。请减少启用的插件或工具后重试。",
  );
  expect(publicExecutionErrorMessage("Different failure")).toBe(
    "Different failure",
  );
});

it.each([
  "http_400: Error from provider (Console): Upstream request failed: Model is unavailable.",
  JSON.stringify({ message: JSON.stringify({ error: { code: "model_not_found" } }) }),
])("explains unavailable models in saved and live failures", (error) => {
  const expected = "所选模型当前不可用，请在输入框选择其他模型后重试。";
  expect(publicExecutionErrorMessage(error)).toBe(expected);
  expect(getStreamErrorMessage(new Error(error), "network failure")).toBe(expected);
});

it("distinguishes Zen engine restrictions from unavailable models", () => {
  const message = "http_400: Error from provider (Console): OpenCode's free tier can only be used in OpenCode";
  expect(publicExecutionErrorMessage(message)).toBe(
    "当前 Zen 免费模型仅支持 OpenCode 引擎，请在输入框切换引擎后重试。",
  );
  expect(publicExecutionErrorMessage("Service temporarily unavailable")).toBe(
    "Service temporarily unavailable",
  );
});

describe("getStreamErrorMessage", () => {
  it("maps missing stream endpoints to a product message", () => {
    expect(
      getStreamErrorMessage(new Error("Stream failed: 404"), "friendly"),
    ).toBe("friendly");
  });

  it("maps unavailable stream endpoints to a product message", () => {
    expect(
      getStreamErrorMessage({ message: "Stream failed: 503" }, "friendly"),
    ).toBe("friendly");
  });

  it("preserves specific non-endpoint errors", () => {
    expect(getStreamErrorMessage("Model timed out", "friendly")).toBe(
      "Model timed out",
    );
  });
});
