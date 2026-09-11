import { expect, it } from "vitest";
import { supportedReasoningEfforts } from "./execution-capabilities";

it("does not infer thinking options from unknown or explicitly unsupported capabilities", () => {
  expect(supportedReasoningEfforts()).toEqual([]);
  expect(supportedReasoningEfforts({ reasoning_efforts: [] })).toEqual([]);
  expect(
    supportedReasoningEfforts({
      reasoning_efforts: ["high"],
      supports_reasoning_effort: false,
    }),
  ).toEqual([]);
  expect(
    supportedReasoningEfforts({
      reasoning_efforts: ["high", "future", "max", "high"],
    }),
  ).toEqual(["high", "max"]);
});
