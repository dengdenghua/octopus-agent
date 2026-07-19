import { expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import {
  PromptInput,
  PromptInputSpeechButton,
  PromptInputSubmit,
} from "@/components/ai-elements/prompt-input";
import { renderWithProviders } from "@/test/harness";

import { Banner } from "./banner";

it("localizes shared dismiss and upload controls", () => {
  renderWithProviders(
    <>
      <Banner onDismiss={vi.fn()}>提示内容</Banner>
      <PromptInput disabled onSubmit={vi.fn()}>
        <span>输入区域</span>
        <PromptInputSpeechButton />
        <PromptInputSubmit />
      </PromptInput>
    </>,
    { locale: "zh-CN" },
  );

  expect(screen.getByRole("button", { name: "关闭" })).toBeInTheDocument();
  const fileInput = screen.getByLabelText("添加附件");
  expect(fileInput).toHaveAttribute("type", "file");
  expect(fileInput).toHaveAttribute("title", "添加附件");
  expect(fileInput).toBeDisabled();
  expect(screen.getByRole("button", { name: "发送" })).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "开始语音输入" }),
  ).toBeInTheDocument();
});

it.each([
  ["ja-JP" as const, "送信", "停止"],
  ["ko-KR" as const, "보내기", "중지"],
])("localizes submit states in %s", (locale, send, stop) => {
  renderWithProviders(
    <PromptInput onSubmit={vi.fn()}>
      <PromptInputSubmit />
      <PromptInputSubmit status="streaming" />
    </PromptInput>,
    { locale },
  );

  expect(screen.getByRole("button", { name: send })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: stop })).toBeInTheDocument();
});
