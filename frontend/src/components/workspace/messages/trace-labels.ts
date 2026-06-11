const TRACE_LABEL_PREFIX =
  /^\s*(?:[-*+]\s+|\d+[.)]\s+)?(?:Thought|Action|Observation|Final Answer|\u601d\u8003|\u601d\u8003\u4e2d|\u60f3\u6cd5|\u6267\u884c|\u6267\u884c\u4e2d|\u884c\u52a8|\u89c2\u5bdf|\u6700\u7ec8\u7b54\u6848)\s*[:\uff1a]\s*/i;

export function stripTraceLabelPrefixes(value?: string | null): string {
  return (value ?? "")
    .split(/\r?\n/)
    .map((line) => {
      let next = line;
      while (TRACE_LABEL_PREFIX.test(next)) {
        next = next.replace(TRACE_LABEL_PREFIX, "");
      }
      return next.trimEnd();
    })
    .join("\n")
    .trim();
}
