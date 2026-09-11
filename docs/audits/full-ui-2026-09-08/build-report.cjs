const fs = require('node:fs');
const path = require('node:path');
const { findings, blockers } = require('./audit-data.cjs');
const dir = __dirname;
const root = 'D:/echo agent';
const all = JSON.parse(fs.readFileSync(path.join(dir,'manifest.json'),'utf8'));
const aliases = JSON.parse(fs.readFileSync(path.join(dir,'route-aliases.json'),'utf8'));
const rejected = new Map();
function exclude(names, reason) { for (const n of names.split(' ')) rejected.set(n,reason); }
exclude('13-workspace-selector 17-preview-panel 17-preview-panel-ready 23-settings-usage 62-plugins-all 63-plugins-installed 89-design-skill-detail 99-subscriptions-configured 100-subscriptions-history 124-market-detail 154-desktop-local-apps 160-browser-extensions 161-browser-ai 169-photos 177-thread-tools 181-tool-output','瞬时加载或未完成渲染，不作为目标流程已验证证据；优先使用后续稳定状态。');
exclude('50-model-connectors 54-multi-model 54-multi-model-form 167-browser-themes 168-browser-home-settings 186-project-space 199-model-connectors-dark 231-browser-settings 232-browser-settings-desktop 233-browser-settings-ready','目标窗口未真正打开或名称与实际视图不一致；后续已补拍对应实际入口。');
exclude('25-settings-conversation-bottom 41-reset-confirmation','重复或名称不准确的中间截图，已有其他有效证据。');
exclude('139-architecture-cerebrum 139-architecture-chromatophores','正文已访问，但截图内代码或图示仍未稳定；不将该两份文档的图示渲染算作通过。');

const groups = [
 ['对话与输入','入口可用，状态提示需优化'],['设置','15 类均已查看；滚动及深链接需修复'],['HUB 与插件','目录可达，技能详情和标识需优化'],['角色与 HUD','配置可达，头像及信息密度需优化'],['项目管理','空态和创建表单可达；已有项目流程未验证'],['设计画布','页面可达，浮层和窄屏需修复'],['叙事工坊','空态和创建窗口可达；实际创作未验证'],['模拟炒股','当前认证部署阻塞'],['订阅与自动化','列表和创建表单可达；调度执行未验证'],['自进化与治理','面板可达；指标语义需优化'],['社区与集市','可达；示例数据、封面和发布表单需优化'],['存储与知识','部分可达；存储及权限阻塞'],['渠道配置','26 个窗口可达；未连接或保存'],['本机助手与桌面整理','只读检查；原生动作未执行'],['架构文档','目录可达；Mermaid 缺字，2 份图示未验'],['可观测性与诊断','部分权限阻塞；窄屏布局需修复'],['反射规则','监控可达，编辑器文件读取阻塞'],['浏览器与桌面','入口可达；设置语义及窄屏浮层需修复'],['图片与视频','索引服务阻塞'],['公共入口与路由','已登录跳转可达；设置深链接失败、分享错误态需优化']
 ];
function groupOf(n) {
 const id = Number(n.split('-')[0]);
 if(id===241) return 3;
 if(id===240||id===242) return 20;
 if(id===235) return 2;
 if(id===236||id===237||id===238) return 4;
 if(id===239) return 16;
 if(id>=225&&id<=234) return 18;
 if(id===221) return 13; if(id===222) return 14; if(id===223) return 15; if(id===224) return 16;
 if(id===220) return 11; if(id===219) return 10; if(id===218) return 9; if(id>=216&&id<=217) return 7;
 if(id>=209&&id<=215) return 6; if(id>=206&&id<=208) return 5; if(id>=201&&id<=205) return 3;
 if(id>=195&&id<=200) return 2; if(id===192||id===193||id===194) return 1;
 if(id>=187&&id<=191) return 20; if(id>=173&&id<=186) return 1;
 if(id===171||id===172) return 20; if(id===169||id===170) return 19;
 if(id>=153&&id<=168) return 18; if(id>=150&&id<=152) return 17;
 if(id>=140&&id<=149) return 16; if(id>=137&&id<=139) return 15;
 if(id>=133&&id<=136) return 14; if(id>=130&&id<=132) return 13;
 if(id>=126&&id<=129) return 12; if(id>=119&&id<=125) return 11;
 if(id>=103&&id<=118) return 10; if(id>=98&&id<=102) return 9;
 if(id===96||id===97) return 8; if(id>=93&&id<=95) return 7;
 if(id>=80&&id<=92) return 6; if(id>=77&&id<=79) return 5;
 if(id>=68&&id<=76) return 4; if(id>=56&&id<=67) return 3;
 if(id>=20&&id<=55) return 2; return 1;
}
const corrections = {
 '63-plugins-installed-ready':'已安装视图加载后显示 4 个插件，未确认推荐与已安装数量不一致；不执行启停或卸载。',
 '161-browser-ai-ready':'Chrome 应用商店网页最终已加载，AI 侧栏可见。未安装扩展或发送任务；已关闭审计新开的外部标签。',
 '165-browser-widgets':'“添加小组件”直接创建默认小组件，未打开目录；仅审计新增的“新小组件”随后已删除撤回。',
 '184-terminal':'终端显示“终端连接失败。点击重启以重新连接。”；这是受阻状态，不是正常空态。未重启或执行命令。',
 '142-observability-resources':'资源页可打开，但带有管理员权限错误及内部接口说明；不能验证受限指标。',
 '146-diagnostics-flags':'功能开关列表可以加载；页面其他区域存在管理员权限错误，不应把整个开关列表标为读取失败。未修改开关。',
 '208-project-members-bottom':'成员高级配置有内外滚动；本次截图没有确认手机端创建和取消按钮最终可达，不将它记为通过。',
 '223-architecture-mobile':'架构页面在手机宽度按纵向排布，目录较长；未观察到先前笔记所称的固定侧栏挤压正文。缺少全局导航入口。',
 '224-observability-mobile':'四个页签分成两行，第二行与下方卡片重叠；首屏介绍过长且缺少全局导航。',
 '213-canvas-help':'帮助项可见，但打开后画布底部工具栏及页面滚动位置变化，需检查覆盖层布局。',
 '228-browser-wallpaper':'壁纸面板已打开；部分缩略图未确认最终加载状态，不据此报告图片服务故障。',
 '138-architecture-mermaid':'稳定后图形与连线存在、节点文字缺失；DOM 标签为空。',
 '190-login-authenticated':'当前已经登录，访问登录页会返回工作区；未退出账号检查登录表单。',
 '191-register':'当前已经登录，访问注册页会返回工作区；未创建账号，也未验证退出登录后的注册流程。'
};
const titleMap = {
 '01-new-task':'新任务首屏','13-workspace-selector-ready':'工作区选择失败回退','27-api-connect-dialog':'模型接入表单','68-agent-switcher':'角色切换菜单','138-architecture-mermaid':'架构 Mermaid 图','175-existing-thread':'历史研究任务','184-terminal':'终端连接错误','193-newtask-390':'手机宽度新任务','224-observability-mobile':'手机宽度可观测性','234-browser-settings-pointer':'浏览器桌面设置','240-settings-deeplink-settled':'设置深链接最终状态','241-agent-create-route':'独立角色创建页','242-share-invalid':'失效分享错误页'
};
const issueByName = new Map();
for(const f of [...findings,...blockers]) for(const n of f.evidence) issueByName.set(n,[...(issueByName.get(n)||[]),f.id]);
const blockedNames = new Set(blockers.flatMap(x=>x.evidence).concat(['97-paper-watch-blocked','151-reflex-editor']));
function screenshotSize(name) { const b=fs.readFileSync(path.join(dir,name+'.png')); return [b.readUInt32BE(16),b.readUInt32BE(20)]; }
const unique = [...new Map(all.map(e=>[e.name,e])).values()];
const accepted = unique.filter(e=>!rejected.has(e.name)).map((e,i)=>{
 const g=groupOf(e.name), issues=issueByName.get(e.name)||[];
 let title=titleMap[e.name]||e.name.replace(/^\d+-/,'').replaceAll('-',' ');
 if(e.name.startsWith('131-channel')) {
  const txt=fs.readFileSync(path.join(dir,e.name+'.txt'),'utf8');
  const m=txt.match(/heading (.*?), Value:/); if(m)title=m[1];
 }
 return {...e,step:i+1,group:g,groupName:groups[g-1][0],title,status:blockedNames.has(e.name)?'功能阻塞':issues.length?'需优化':'已查看',issues,note:corrections[e.name]||e.note||'已打开并检查此页面或窗口的可见状态；此记录不代表提交、执行或连接成功。',dimensions:screenshotSize(e.name)};
});
const exclusions=unique.filter(e=>rejected.has(e.name)).map(e=>({name:e.name,reason:rejected.get(e.name)}));
const safe=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const abs=(name,ext='png')=>(dir+'/'+name+'.'+ext).replaceAll('\\','/');
const localLink=(label,file)=>`[${label}](<${file}>)`;
const imageMd=n=>`![${titleMap[n]||n}](<${abs(n)}>)`;
const counts={captured:unique.length,retained:accepted.length,excluded:exclusions.length,findings:findings.length,blockerGroups:blockers.length,groups:groups.length,aliasChecks:aliases.length};
fs.writeFileSync(path.join(dir,'accepted-manifest.json'),JSON.stringify({counts,scope:'截图状态的视觉与入口审核；不是端到端功能通过率。',entries:accepted,exclusions},null,2));
let review=`# Echo 前端完整走查记录\n\n日期：2026-09-08。环境：本地前端 3310 / 后端 8310，已登录账号，Windows 内置浏览器。\n\n本轮覆盖当前数据和权限下可到达的页面、菜单、设置分区及创建前窗口。主对话已较克制，优先要补齐的是滚动与焦点、跨模块导航、可信状态和错误恢复。没有改动业务代码。\n\n本轮捕获 **${counts.captured}** 个屏幕状态，保留 **${counts.retained}** 个可复核记录（包括明确标注的错误状态），排除 **${counts.excluded}** 个加载中、重复或错位记录；整理 **${findings.length}** 项优化发现和 **${blockers.length}** 组功能阻塞。这些数量不是测试通过数。\n\n${localLink('全部逐步截图和说明',abs('steps','md'))} · ${localLink('可筛选截图画廊',abs('gallery','html'))} · ${localLink('结构化证据清单',abs('accepted-manifest','json'))}\n\n## 逐项覆盖\n\n|步骤|页面/流程|范围|当前健康度|\n|---|---|---|---|\n`;
const coverage=[
 '输入插入菜单、权限、引擎、模型、模式、工作区、协作、侧栏、助手、历史任务、回放和五类右侧面板；800px 与 390px',
 '账号、订阅与用量、通用、对话、模型、记忆、通知、编码、工具、浏览器自动化、桌面自动化、执行与安全、个人空间与安全、诊断、关于；API/Connector/多模型/重置确认窗口',
 '角色、应用、Skills；推荐/全部/已安装/远程 Agent；新建菜单、角色生成、团队、远程注册和角色详情',
 '切换、档案、成长、雷达、技能树、基础配置、ARM、白名单、权限、路由和预算；手机布局',
 '列表空态、创建、成员高级配置；桌面和手机',
 '创作首页、指南、模型菜单、工作流/自由画布、节点菜单、设置/帮助/快捷键、资产、添加资产、技能详情、ComfyUI、环境和导入；手机布局',
 '首页、能力面板、新建项目；手机布局',
 '首页及当前部署的认证限制状态',
 '任务、已配置、历史、面板、新建自动化；手机布局',
 '实验、候选、部署、治理、策略、技能/模型/MCP、课程、框架、漂移、A/B、反射和运行设置；手机布局',
 '发现、信息流、评论、发布、集市、商品详情、上架；手机布局',
 '存储、知识图谱、记忆、Wiki；图片视频依赖另列',
 '总览、26 个独立渠道配置窗口、响应对象选择；手机布局',
 '设备/控制工作区、动作菜单、桌面整理；手机布局',
 '目录 13 份文档入口、正文和图形；两份图示未稳定，单独列入限制',
 '总览、事件、资源、系统；运行、流式、开关、建议、远程和不变量；诊断直达与手机布局',
 '监控、编辑器、源码读取失败态',
 '独立桌面/浏览器、下载、历史、书签、更多、外部网页、AI 侧栏、编辑态、图标、文件夹、组件、主题、壁纸、娱乐、应用和设置；手机布局',
 '图片和视频索引的稳定错误状态',
 '介绍、条款、隐私、已登录下登录/注册跳转、无邀请团队入口、无 URL 网页应用、无效分享、15 条重定向别名'
];
groups.forEach((g,i)=>review+=`|${i+1}|${g[0]}|${coverage[i]}|${g[1]}|\n`);
review+='\n## 优先修复顺序\n\n1. 恢复核心配置和任务路径：F02、F03、F04，并排查 B01–B03 对应服务状态。\n2. 修复功能语义与可读性：F01、F05、F06、F11、F12、F18。\n3. 完成共用移动布局、弹窗与可访问性：F07–F10、F14、F16。\n4. 收敛视觉密度、头像、封面和说明：F13、F15、F17、F19、F20。\n\nP1 表示直接打断关键配置流程；P2 表示明显影响理解、操作或一致性。优先级是本轮体验判断，不是安全漏洞等级。\n\n## 具体发现\n';
for(const f of findings){
 review+=`\n### ${f.id} · ${f.priority} · ${f.title}\n\n**观察：** ${f.observation}\n\n**影响：** ${f.impact}\n\n**建议：** ${f.fix}\n\n**验收：** ${f.acceptance}\n\n**证据强度：** ${f.confidence}。\n`;
 if(f.sources.length)review+='\n代码定位：'+f.sources.map(([p,l])=>localLink(p.split('/').pop()+':'+l,root+'/'+p+':'+l)).join(' · ')+'\n';
 review+='\n证据：'+f.evidence.map(n=>localLink(n,abs(n))).join(' · ')+'\n\n'+imageMd(f.evidence[0])+'\n';
}
review+='\n## 功能阻塞，不能记为通过\n';
for(const b of blockers)review+=`\n### ${b.id} · ${b.title}\n\n${b.note}\n\n${b.evidence.map(n=>localLink(n,abs(n))).join(' · ')}\n\n${imageMd(b.evidence[0])}\n`;
review+='\n## 路由跳转复核\n\n|输入路径|实际落点|结果|\n|---|---|---|\n';
for(const a of aliases)review+=`|\`${a.route}\`|\`${a.url.split('#')[1]}\`|${a.route==='/settings'||a.route==='/workspace/mcp'?'未打开应有设置弹窗（F04）':'跳转方向符合当前路由定义'}|\n`;
review+='\n## 渠道窗口明细\n\n'+accepted.filter(e=>e.name.startsWith('131-channel')).map(e=>`- ${e.title}：已打开字段配置，未连接或保存。${localLink('截图',abs(e.name))}`).join('\n')+'\n';
review+=`\n## 验证边界与恢复\n\n- 本轮检查菜单、选项、表单和最终可见状态，没有发任务、重跑历史任务、安装/卸载插件、接入外部账号、发布、下单、部署或创建业务数据。插件权限确认链路不能保证只读：源码中部分市场安装按钮会直接安装，故未点击；需要后续专门验证安装与授权完整闭环。\n- 已登录态下登录/注册会回到工作区；未退出当前账号。因此未验证登录表单、密码恢复、新用户引导和注册提交。无有效分享或团队邀请 token，仅验证缺失/失效状态。\n- 项目和叙事没有现成数据可进入编辑及详情；未为审计创建项目。ComfyUI 的本地依赖不可用，未跑生成。存储、模型任务恢复、交易和管理员数据按 B01–B03 记录。\n- Windows 原生桌面窗口控制、macOS/Linux 原生边框、系统目录选择器、原生权限和真实触屏设备未实测；此轮结论只覆盖浏览器及其回退界面。\n- 架构 Cerebrum 与 Chromatophores 已访问正文，但对应两张图示截图未稳定；这两份文档的图示渲染未验证。未把加载中或抓错窗口的图片作为完成证据。\n- 视口包括 1280×720、800×700、390×844，以及恢复后的实际浏览器尺寸；按每张 PNG 的真实尺寸记录。深浅主题做了代表页面检查，并非所有窗口均穷举两种主题及所有宽度。\n- 可访问性通过可见焦点、部分 Escape 行为和可访问树抽查；未做完整读屏、色差仪或 WCAG 合规测试。\n- 临时主题已恢复为跟随系统/蔷薇粉/舒适 15px；画布恢复工作流及创作首页；审计误新增的默认小组件已删除，仅关闭审计新开的外部网页。原用户浏览器标签未被操作。视口覆盖已重置。\n- 只新增本审计目录的文档与截图，没有改动应用代码、重启服务或提交代码。已有工作区修改保留。\n\n## 证据排除清单\n\n`;
for(const e of exclusions)review+=`- ${e.name}：${e.reason}\n`;
fs.writeFileSync(path.join(dir,'review.md'),review);

let steps=`# 逐步截图与状态\n\n${localLink('返回问题清单',abs('review','md'))} · ${localLink('可筛选画廊',abs('gallery','html'))}\n\n以下 ${accepted.length} 条仅记录本轮检查过的可见状态。“已查看”不表示提交、连接或执行通过；“功能阻塞”仅保留错误证据。原始截图文件名保留捕获顺序，以下步骤号为排除中间状态后的顺序。\n`;
for(const e of accepted)steps+=`\n## ${e.step}. ${e.groupName} · ${e.title}\n\n**状态：${e.status}** · 视口 ${e.dimensions.join(' × ')} · ${e.issues.length?'关联 '+e.issues.join('、'):'未在此状态单列缺陷'}\n\n${e.note}\n\n路径：\`${e.url.split('#')[1]}\`\n\n${imageMd(e.name)}\n`;
fs.writeFileSync(path.join(dir,'steps.md'),steps);
const css=`:root{font-family:system-ui,'Microsoft YaHei',sans-serif;color:#202124;background:#f5f5f4}*{box-sizing:border-box}body{margin:0}header{background:white;padding:24px 32px;border-bottom:1px solid #ddd}h1{font-size:25px;margin:0 0 12px}p{line-height:1.7}a{color:#91495d}nav{display:flex;gap:16px}form{position:sticky;top:0;z-index:2;background:#fff;padding:12px 32px;display:flex;gap:10px;flex-wrap:wrap;border-bottom:1px solid #ddd}input,select{font:inherit;padding:9px 12px;border:1px solid #bbb;border-radius:7px}input{flex:1;min-width:180px}main{padding:24px 32px;display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:20px}article{background:#fff;border:1px solid #ddd;border-radius:10px;padding:18px;min-width:0}article[hidden]{display:none}h2{font-size:16px;line-height:1.5;margin:0 0 10px}article p{font-size:13px;margin:10px 0}article img{width:100%;height:280px;object-fit:contain;background:#f9f9f9;border:1px solid #eee}small{display:block;color:#666;overflow-wrap:anywhere}.badge{display:inline-block;padding:3px 8px;border-radius:5px;background:#eee;font-size:12px}.issue{background:#fff2d8}.blocked{background:#ffe5e5}footer{padding:0 32px 30px;color:#666}@media(max-width:500px){header,form,main{padding:16px}main{grid-template-columns:1fr}}`;
const cards=accepted.map(e=>`<article data-status="${e.status}" data-group="${e.group}" data-search="${safe([e.name,e.title,e.groupName,e.note,...e.issues].join(' ').toLowerCase())}"><h2>${e.step}. ${safe(e.groupName)} · ${safe(e.title)}</h2><span class="badge ${e.status==='需优化'?'issue':e.status==='功能阻塞'?'blocked':''}">${e.status}</span> <span>${e.issues.join(' · ')}</span><p>${safe(e.note)}</p><a href="${e.name}.png" target="_blank"><img loading="lazy" src="${e.name}.png" alt="${safe(e.title)}"></a><small>${safe(e.name)} · ${e.dimensions.join(' × ')}<br>${safe(e.url.split('#')[1])}</small></article>`).join('\n');
const html=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Echo 完整前端走查</title><style>${css}</style></head><body><header><h1>Echo · 完整前端走查</h1><p>2026-09-08 · ${counts.retained} 个保留状态 · ${findings.length} 项发现 · ${blockers.length} 组阻塞。截图状态不等于端到端测试通过。</p><nav><a href="review.md">问题与验收清单</a><a href="steps.md">逐步记录</a><a href="accepted-manifest.json">证据索引</a></nav></header><form onsubmit="return false"><input id="search" type="search" aria-label="搜索页面、窗口或问题编号" placeholder="搜索页面、窗口或 F01…"><select id="group" aria-label="筛选模块"><option value="">全部模块</option>${groups.map((g,i)=>`<option value="${i+1}">${g[0]}</option>`).join('')}</select><select id="status" aria-label="筛选状态"><option value="">全部状态</option><option>需优化</option><option>功能阻塞</option><option>已查看</option></select><output id="count" aria-live="polite">${accepted.length} 条</output></form><main>${cards}</main><footer>未执行安装、连接、发送、发布、购买等提交动作；详情及限制见问题清单。点击截图可查看原图。</footer><script>const search=document.querySelector('#search'),group=document.querySelector('#group'),status=document.querySelector('#status'),items=[...document.querySelectorAll('article')];function filter(){let n=0;for(const e of items){const show=(!group.value||e.dataset.group===group.value)&&(!status.value||e.dataset.status===status.value)&&e.dataset.search.includes(search.value.trim().toLowerCase());e.hidden=!show;if(show)n++;}document.querySelector('#count').textContent=n+' 条';}[search,group,status].forEach(e=>e.addEventListener('input',filter));</script></body></html>`;
fs.writeFileSync(path.join(dir,'gallery.html'),html);
fs.writeFileSync(path.join(dir,'summary.json'),JSON.stringify(counts,null,2));
for(const f of [...findings,...blockers])for(const n of f.evidence)if(!accepted.some(e=>e.name===n))throw Error('Unaccepted evidence: '+n);
console.log(JSON.stringify(counts));
