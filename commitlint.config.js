export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    // 常见提交类型显式声明，方便新人即看即用。
    // 打字错误不会让 commit 失败（config-conventional 只检查格式）。
    'type-enum': [
      2,
      'always',
      [
        'feat',     // 新功能
        'fix',      // 修复
        'docs',     // 文档
        'style',    // 格式、空白、分号（非逻辑变更）
        'refactor', // 重构，不改行为
        'perf',     // 性能优化
        'test',     // 测试
        'build',    // 构建系统/依赖
        'ci',       // CI 配置
        'chore',    // 杂项
        'revert',   // 回滚
        'wip',      // 进行中，禁止合并
        'release',  // 发版
        'deps',     // 依赖升级/回退
      ],
    ],
    // header/body 行宽压到 72，超过则 GitHub/GitLab 预览会截断。
    'header-max-length': [2, 'always', 72],
    'body-max-line-length': [2, 'always', 72],
    'footer-max-line-length': [2, 'always', 72],
    // body/footer 与 header 之间保留空行，Conventional Commits 规范要求。
    'body-leading-blank': [2, 'always'],
    'footer-leading-blank': [2, 'always'],
    // 关闭 subject 大小写检查：团队大量使用中文 subject，
    // 比如 `feat: 新增登录页` 不应被强制要求小写开头。
    'subject-case': [0],
  },
};
