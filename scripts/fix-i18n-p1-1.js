const fs = require('fs');
const path = require('path');

const targets = [
  { file: 'frontend/src/core/i18n/locales/ja-JP.ts', replacements: [
    ['    chats: "Tasks",', '    chats: "Chats",'],
    ['    demoChats: "Demo tasks",', '    demoChats: "Demo chats",'],
  ]},
  { file: 'frontend/src/core/i18n/locales/zh-CN.ts', replacements: [
    ['    deleteThreadTooltip: "删除任务",', '    deleteThreadTooltip: "删除对话",'],
  ]},
];

for (const { file, replacements } of targets) {
  const p = path.join(process.cwd(), file);
  let s = fs.readFileSync(p, 'utf8');
  let changed = 0;
  for (const [oldStr, newStr] of replacements) {
    if (s.includes(oldStr)) {
      s = s.replace(oldStr, newStr);
      changed++;
    } else {
      console.log('[skip-not-found]', file, oldStr);
    }
  }
  fs.writeFileSync(p, s, 'utf8');
  console.log('[ok]', file, 'replacements:', changed);
}
