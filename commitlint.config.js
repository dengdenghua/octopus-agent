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
      ],
    ],
  },
};
