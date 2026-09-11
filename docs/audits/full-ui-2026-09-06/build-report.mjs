import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const dir=path.dirname(fileURLToPath(import.meta.url));
const rows=JSON.parse(fs.readFileSync(path.join(dir,'coverage.json'),'utf8'));
const issues=JSON.parse(fs.readFileSync(path.join(dir,'findings.json'),'utf8'));
const h=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const superseded={1:256,8:257,9:257,10:258,11:259,12:273,42:294,49:301,149:297,272:326};
const excluded=new Set([7,50]);
const blocked=new Set([16,53,109,110,111,112,113,114,115,116,117,118,119,120,121,122,130,131,133,138,142,144,160,168,169,184,199,203,204,205,234,235,239,240,253,258,275,292,296,319,326]);
const partial=new Set([6,19,43,94,143,247,248,249,250,251,261,265,271,316,323]);
const groups=[
 ['对话与工作台',[[1,13],[256,282],[304,305],[308,310],[318,319],[325,326]]],
 ['设置与模型',[[14,48],[289,294],[306,307],[320,320]]],
 ['HUB与插件',[[49,62],[299,303],[311,311],[321,321]]],
 ['项目管理',[[63,65]]],['设计画布',[[66,98],[313,317],[322,322]]],
 ['叙事工坊',[[99,101]]],['订阅与自动化',[[102,108]]],
 ['自进化',[[109,122],[295,295]]],['社区与市场',[[123,129]]],
 ['模拟炒股',[[130,131]]],['本地数据库',[[132,141],[296,296]]],
 ['知识库',[[142,144]]],['可观测性与诊断',[[145,154],[297,298],[323,324]]],
 ['架构与规则',[[155,169]]],['26种渠道',[[170,198]]],
 ['电脑与独立应用',[[199,205]]],['AI浏览器',[[206,233]]],
 ['公开页与认证',[[234,240]]],['导航与角色配置',[[241,255],[312,312]]],
 ['常驻助手',[[283,288]]]
];
rows[9].notes='首次邀请尝试未得到可作为稳定表单证据的截图；以258的复核阻断为准。未生成或发送邀请。';
rows[42].notes='矩阵总数14，当前仅显示8；源码 model-settings-page.tsx:2341 使用 slice(0,8)，缺少全部展开入口。';
rows[242].notes='Zero角色档案强制深色；现实职业简介与现场执行官、创意叙事委托文案不一致。点击过程不能支持“默认打开错误角色”的结论，已剔除该判断。';
rows[269].notes='工具列表名称技术化且相近，点击后的详情见271；不据此断言存在可用的第三层参数面板。';
rows[271].notes='原截图未保持可见浮层，不作为弹层细节证据；复核326仍未获得稳定详情。';
rows[284].notes='自动化已配置空态说明可读；“不再提示”已开但当前仍显示提示，生效时机不明确，未验证下次会话行为。';
rows[323].notes+=' 原因默认 scheduled rotation，关闭可访问名称仍为 Close；字段有可访问名称。';
for(const r of rows){
 r.area=groups.find(([,ranges])=>ranges.some(([a,b])=>r.step>=a&&r.step<=b))?.[0]??'其他';
 r.status=excluded.has(r.step)?'作废':superseded[r.step]?'已替代':blocked.has(r.step)?'受阻或条件未验证':partial.has(r.step)?'部分取证':'已取证';
 if(superseded[r.step])r.supersededBy=superseded[r.step];
 if(excluded.has(r.step))r.notes='未获得目标稳定状态，保留审计轨迹，不纳入有效目标窗口证据。';
 if(!r.notes)r.notes='已打开并检查该页面或菜单的当前可见状态；未发现需独立列项的问题，后续提交和数据依赖流程不等同已验证。';
 r.findings=issues.filter(i=>i.evidence.includes(r.step)).map(i=>i.id);
 r.viewport=r.step>=304&&r.step<=306?'900×700':r.step>=307&&r.step<=319?'390×844':'桌面';
 r.health=r.status==='作废'||r.status==='已替代'?r.status:r.findings.length?'需整改':r.status==='已取证'?'已检查当前状态':'受限，未判定通过';
}
const evidence=n=>rows[n-1];
const mdLink=(n)=>`[${String(n).padStart(3,'0')} ${evidence(n).name}](${evidence(n).screenshot})`;
const routes=[
 ['对话、新任务、常驻助手','realtime/new、realtime/:id、realtime/octopus-assistant','菜单、权限、引擎、协作、分享、重命名、删除、工作台、回放、助手自动化','2–13、256–288、304–310、318–319、325–326','邀请与原生选择受阻；未发送新任务、再生成或分享快照。'],
 ['HUB','agents：角色/应用/Skills','推荐、全部、已安装、远程Agent、权限预检、添加角色、组队、角色详情、搜索、分页','51–62、299–303、311','角色421条和插件列表复用组件；未逐条安装，未将记录数量当窗口数量。'],
 ['设置','settings及全局设置弹窗','15个设置分类、模型接入、请求头、兼容矩阵、隐私高级、沙箱、危险确认、各下拉','14–48、289–294、306–307、320','订阅付费、第三方账号、成功原生选择器不可达；未改变业务配置。'],
 ['项目管理','projects','列表空态、创建、成员设置','63–65','协作项目为空，任务详情/项目删除/成员邀请等数据后续流程未创建测试项目验证。'],
 ['设计画布','design iframe','首页、图像/视频/音频模型、项目、资产、Skill、ComfyUI、已有画布、节点/布局/帮助/反馈窗口','66–98、313–317、322','未新增或运行节点；节点类型对应专用编辑器、导入文件和运行后产物受数据/原生边界限制。'],
 ['叙事工坊','narrative iframe','项目空态、创建、MCP/Skill说明','99–101','没有现有叙事项目；章节、正典、分支与协同细节未通过创建数据进入。'],
 ['订阅','intelligence iframe','模板、创建、频率/每周、已配置、历史、面板','102–108','未创建计划；编辑/暂停/删除/执行详情需要计划及运行数据。'],
 ['自进化','evolution iframe','概览、实验、候选、部署、安全、预算/技能/模型/MCP/课程/框架/漂移/AB、规则及运行设置','109–122、295','权限/服务拒绝阻断有效数据；晋升、回滚、门禁覆盖未验证。'],
 ['发现社区及市场','community iframe','社区、帖子、作者、发帖草稿、市场、商品详情、上架草稿','123–129','未发布、购买、点赞或评论；交易成功流程未验证。'],
 ['模拟炒股','paper-trading iframe','应用入口、监控入口的禁用状态','130–131','安全配置禁用；交易、订单、持仓窗口未验证。'],
 ['本地数据库','storage：computer/apps/docs/images/videos','本机、源目录、授权、文档、图片、人物、标签、最近、策略','132–141、296','NAS 502，人物页崩溃；文件详情/编辑/移动/删除/模型下载、成功扫描流程未验证。'],
 ['知识库','knowledge','图谱、记忆资产、Wiki','142–144','图谱权限拒绝、记忆为空、Wiki未选项目；详情与编辑依赖数据。'],
 ['可观测性','observability及diagnostics别名','总览、事件流、资源成本、系统；流式、开关、建议、远程、不变量、诊断；发布者轮换表单','145–154、297–298、323–324','管理员数据不可用；恢复/应用/重放会产生任务或变更，未触发；吊销需已注册密钥。'],
 ['架构与规则','architecture、reflex、reflex/edit','架构13个文档入口、规则列表与编辑错误态','155–169','ReAct文档404；规则崩溃/编辑403，规则表单后续未验证。'],
 ['渠道','channels','全部26种渠道的配置窗口、AI分配选择、微信二维码错误态','170–198','没有已连接渠道；配对列表和成功连接回执需真实账号。'],
 ['电脑与独立应用','computer、desktop-organizer、desktop、apps/photos、apps/media、web-app','电脑动作菜单、整理器、桌面入口、媒体/照片错误态、Web应用缺URL状态','199–205','网页原生能力和依赖服务受限；未启动桌面任务。'],
 ['AI浏览器','browser','主页、更多、隐私、历史、下载、书签、助手、角色、编辑/文件夹/图标/小组件、主题/壁纸/娱乐/应用/设置、搜索引擎、标签抽屉','206–233','站点信息、页内查找、网页设备权限、密码管理需要真实webview；清数据/重置布局未确认，未审查所有外部网站。'],
 ['公开页面','about、terms、privacy、share、login、register、team/join','关于、条款、隐私、无效分享、缺邀请令牌、本地认证重定向','234–240','本地模式无云登录/注册表单；有效邀请/分享及账单未生成。'],
 ['导航与角色','侧栏、账户角色菜单、HUD、快捷键','模块编辑、个人菜单、档案/成长/雷达/技能树、ARM/技能/权限/预算、基础编辑、积分、命令面板、移动两套抽屉','241–255、309–312','未签到或改角色配置；积分兑换与账户绑定需服务和正式账号。'],
 ['响应式与主题','1294×912、900×700、390×844','聊天/工作台恢复、设置、移动历史、HUB、设计画布、系统/深色主题','304–322','桌面浏览器模拟视口，未测真实触屏、软键盘、所有缩放和颜色组合。']
];
const windowRules=[
 ['api-publish-panel.tsx','源码存在，未挂载','未找到运行时调用者，不能从当前导航进入 API 发布窗口。',''],
 ['onboarding/index.tsx','源码存在，未挂载','OnboardingGuide 当前没有运行时挂载。',''],
 ['daily-claim-dialog.tsx','条件未验证','每日签到会写入积分；自动弹窗包装没有当前挂载入口，未执行签到。','252'],
 ['scope-settings.tsx','源码存在，未挂载','ScopeSettingsButton 没有运行时调用者。',''],
 ['paused-tasks-banner.tsx','源码存在，未挂载','PausedTasksBanner 没有运行时调用者。',''],
 ['collab/team-members-dialog.tsx','源码存在，未挂载','仅定义/聚合导出，未找到页面调用。',''],
 ['p2/message-feedback.tsx','源码存在，未挂载','旧反馈组件只有定义/导出；当前消息反馈按钮属于另一实现。',''],
 ['export-trigger.tsx','源码存在，未挂载','当前分享菜单提供HTML导出；旧导出窗口未找到运行时调用。','259'],
 ['reasoning-effort-picker.tsx','源码存在，未挂载','独立推理强度组件没有运行时调用；Coder设置有自己的配置控件。','38'],
 ['workspace-members-panel.tsx','源码存在，未挂载','独立工作区成员面板未找到运行时调用；AI会话成员另有入口。','257'],
 ['mount-point-dialog.tsx','条件未验证','WorkspaceSwitcher 需多于一个工作区；当前单工作区无挂载点配置入口。','6,253,319'],
 ['channel-pairings-sheet.tsx','条件未验证','只有已连接渠道才暴露配对管理；26种渠道都未连接。','170–198'],
 ['ReplayGateOverrideDialog.tsx','条件未验证','需尝试应用晋升项并触发门禁；当前数据/权限不可用，未执行变更。','146,323'],
 ['PublisherTrustCard.tsx','部分已查','轮换窗口已查且取消；吊销/替换现有密钥需真实密钥数据。','323,324'],
 ['pay-order-dialog.tsx','条件未验证','计费服务不可用，套餐购买和订单窗口不可达；未创建订单。','16,292'],
 ['collab/create-task-dialog.tsx','条件未验证','项目任务面板需要现有协作项目；当前项目列表为空。','63,64'],
 ['collab/invite-dialog.tsx','受阻','入口点击未稳定打开，未生成邀请；不把源码字段当已验证界面。','258'],
 ['member-profile-popover.tsx','受阻','两次复核未取得稳定可见浮层。','326'],
 ['messages/subagent-details-panel.tsx','条件未验证','仅并行子任务网格里有入口，当前对话无该类型执行记录。','269,270'],
 ['realtime/project-group-header-badge.tsx','条件未验证','需要已提升的项目群组；当前会话只有提升项目的入口。','279'],
 ['memory-assets-panel.tsx','部分已查','已查空态；资产详情/编辑依赖已有记忆。','143'],
 ['url-bar.tsx','部分已查','更多/隐私/历史/下载已查；站点信息、查找、设备权限与密码需真实桌面webview；清数据确认未触发。','207–212'],
 ['browser-home.tsx','部分已查','所有主面板和草稿编辑已查；重置布局/删除用户条目未执行；设置底层复用聚焦搜索、编辑、回主页、重置四个动作。','206,215–233'],
 ['workbuddy-cloud-store-panel.tsx','部分已查','云目录与权限预检已查；真实安装/授权/连接完成态未执行。','52,53,299,300'],
 ['capability-market-panel.tsx','部分已查','推荐/全部/已安装/远程目录已查；卸载源码直调API，未卸载用户插件。','51–56,299–301'],
 ['workspace/storage/page.tsx','受阻/部分已查','全部库入口和失败态已查；真实文件/模型/扫描详情受NAS502限制。','132–141,296'],
 ['workspace/channels/page.tsx','部分已查','26种凭据窗口均打开；真实连接/配对依赖账号。','170–198'],
 ['channel-credential-dialog.tsx','部分已查','26种动态表单已打开并关闭，没有写入凭据。','171–198'],
 ['app/apps/media/page.tsx','受阻','媒体后端权限拒绝，数据后续窗口未验证。','204'],
 ['workspace/observability/page.tsx','部分已查','全页签与底部卡片已查；请求拒绝及空数据限制后续窗口。','145–154,297–298,323–324'],
 ['workspace/design/page.tsx','部分已查','宿主入口及远端工作台已查；专用节点/运行产物取决于数据。','66–98,313–317,322'],
 ['agents/new/page.tsx','部分已查','新建角色页面已查；没有生成或保存角色。','61'],
 ['ui/confirm-dialog.tsx','复用组件已查','通过聊天删除、重置、组件删除的取消流程检查；非所有业务提交变体。','31,223,282'],
 ['ui/prompt-dialog.tsx','复用组件已查','通过文件夹/图标输入检查并取消。','216–218'],
 ['ui/dialog.tsx','复用组件已查','多个对话框及移动/深色代表状态；不等同每个调用者全状态通过。','21,31,307,324'],
 ['ui/command.tsx','复用组件已查','命令面板/搜索；未执行命令。','254'],
 ['ui/sidebar.tsx','复用组件已查','桌面和移动导航开关、折叠。','241,312,313'],
 ['ChatComposer.tsx','部分已查','主要菜单、空输入、现有任务显示；未发送/再生成/触发原生上传。','273–279,308,318'],
 ['AutomationTargetControl.tsx','受阻','窗口发现持续等待，未取得宿主窗口列表。','275'],
 ['command-palette.tsx','已查当前窗口','命令菜单、快捷键和缺少入口核对。','254,255'],
 ['smart-team-dialog.tsx','已查未提交','空目标时按钮禁用；未创建协作任务。','59'],
 ['browser-preview-panel.tsx','部分已查','预览/选项/标注/日志已查；真实浏览器及发布未验证。','261,265–267'],
 ['agent-world-unified.tsx','部分已查','角色HUD所有数据页签和配置入口；立绘生成、保存未执行。','243–251'],
 ['agent-role-profile-dialog.tsx','部分已查','角色档案、能力配置和编辑入口；未生成立绘。','243–251'],
 ['agent-card.tsx','部分已查','卡片、目录筛选与详情代表；未逐条安装角色。','58,62,302,303'],
 ['agent-arms-dialog.tsx','部分已查','ARM、Skill、权限、预算页；未保存/重置。','247–250'],
 ['credits-center.tsx','部分已查','积分中心已查；签到/购买/兑换未执行。','252'],
 ['create-project-dialog.tsx','已查未提交','创建表单已查并取消。','64,73'],
 ['cowork-room-message-actions.tsx','部分已查','消息操作入口可见；编辑并重发/重试/派生会产生任务，未触发。','256,269'],
 ['evolution-panel.tsx','受阻/部分已查','全页签错误态/运行设置已查，晋升回滚依赖管理员数据。','109–122,295'],
 ['automation-create-dialog.tsx','已查未提交','创建、模板预填、频率/每周均已查；未建立计划。','103–105,288'],
 ['execution-engine-picker.tsx','已查当前窗口','自动/引擎菜单；未更改当前任务执行选择。','3'],
 ['automation-configured-tab.tsx','部分已查','配置列表为空；编辑、启停、删除依赖已有计划。','106,285'],
 ['assistant-settings-menu.tsx','已查当前窗口','助手新会话配置菜单，未修改。','284'],
 ['coder-engine-control.tsx','部分已查','模型来源与运行详情、Connector；未改配置。','18,38,294'],
 ['chats-drawer.tsx','已查当前窗口','手机历史、搜索空态、导航跳转。','309,310'],
 ['workbench-tab-header.tsx','已查当前窗口','标签、隐藏标签列表、右侧窗口关闭恢复。','260–265,304,305'],
 ['intelligence-panel.tsx','部分已查','订阅页签、创建和占位面板；执行后窗口无数据。','102–108'],
 ['model-picker.tsx','已查当前窗口','当前可用模型菜单；不同模型属性变体未逐个选用。','4'],
 ['module-editor-dialog.tsx','已查当前窗口','侧栏模块编辑草稿；未保存变更。','241'],
 ['messages/message-list-item.tsx','部分已查','当前文本、工具组、错误恢复、操作入口；多媒体/审批/子任务变体无当前数据。','256,269–271,326'],
 ['permission-indicator.tsx','已查当前窗口','权限分级及解释；未变更。','2'],
 ['promote-group-to-project-dialog.tsx','已查未提交','目标空值禁用创建；未提交。','279'],
 ['task-collaborator-control.tsx','部分已查','成员选择、来源与邀请入口；未增删成员。','257,258'],
 ['recent-chat-list.tsx','已查当前窗口','会话菜单/重命名/删除确认，均取消。','280–282'],
 ['share-menu.tsx','部分已查','公开只读范围及HTML导出入口；未生成公开链接、二维码或下载文件。','259'],
 ['sidebar-footer.tsx','已查当前窗口','个人角色/积分/设置入口。','242,252'],
 ['subscription-settings-page.tsx','受阻','计费未连接，重试后仍失败。','16,292'],
 ['settings-dialog.tsx','部分已查','所有当前分类与桌面/窄窗/手机主题代表；数据后续表单分列。','14–48,289–294,306,307,320'],
 ['memory-settings-page.tsx','部分已查','记忆页和创建空表单；未新增记忆。','20,21'],
 ['privacy-settings-page.tsx','部分已查','高级配置、阻止路径、出厂重置确认均取消。','28–31'],
 ['mcp-settings-page.tsx','部分已查','MCP集成及空添加表单；未连服务。','24'],
 ['model-settings-page.tsx','部分已查','来源、接入表单、请求头、本地服务、网关、高级协同和矩阵；未测试或保存新模型。','18,19,35–43,294'],
 ['cron-settings-page.tsx','复用/条件未验证','设置自动化入口与订阅共用能力；成功执行、计划详情依赖数据。','102–107,285–288'],
 ['automation-settings-page.tsx','部分已查','浏览器/桌面自动化设置，网页环境原生动作受限。','25,26,289'],
 ['team-mode-picker.tsx','已查当前窗口','按需回复/分工协作/并行共创说明，未修改。','325'],
 ['user-menu.tsx','已查当前窗口','角色与账号菜单、积分入口。','242,252'],
 ['account-settings-page.tsx','部分已查','当前local认证账户说明；云端资料/验证窗口不可达。','15'],
 ['workspace-nav-chat-list.tsx','部分已查','导航列表与更多菜单；新增会话同步受共享后端变化影响。','280–282,309,312'],
 ['workspace-sidebar.tsx','部分已查','编辑/折叠/移动菜单；原生项目选择未验证。','241,253,312,313']
];
const sourceFiles=fs.readFileSync(path.join(dir,'window-source-inventory.txt'),'utf8').trim().split(/\r?\n/).map(s=>s.replaceAll('\\','/'));
const sourceRows=sourceFiles.map(file=>{
 const rule=windowRules.find(([suffix])=>file.endsWith(suffix));
 if(!rule)throw Error('未分类源码窗口: '+file);
 return {file,status:rule[1],reason:rule[2],evidence:rule[3]};
});
const csv=(records,keys)=>'\ufeff'+[keys,...records.map(r=>keys.map(k=>r[k]))].map(r=>r.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n');
fs.writeFileSync(path.join(dir,'coverage.json'),JSON.stringify(rows,null,2));
fs.writeFileSync(path.join(dir,'source-window-coverage.csv'),csv(sourceRows,['file','status','reason','evidence']));
fs.writeFileSync(path.join(dir,'issues.csv'),csv(issues.map(i=>({...i,evidence:i.evidence.join(' ')})),['id','priority','area','title','observation','impact','recommendation','acceptance','evidence']));
const counts=Object.fromEntries([...new Set(rows.map(r=>r.status))].map(s=>[s,rows.filter(r=>r.status===s).length]));
const summary=`本轮保存 ${rows.length} 条编号截图记录，对照 ${sourceRows.length} 个窗口相关源码文件，整理 ${issues.length} 项整改。截图数量包含重复复核、错误态和响应式变体，不是独立窗口数，也不是通过数。`;
let md=`# Echo 前端全量走查记录\n\n${summary}\n\n结论：优先修复数据真实性、故障恢复、任务状态和导航闭环，再收敛界面。现有聊天/设置的基础排版、空值禁用、删除确认和移动适配有可复用的基础。\n\n## 范围与证据边界\n\n- 时间：2026-09-06，Asia/Shanghai；代码库 D:/echo agent。收尾时 HEAD 为 99c9abee33a3af9159b2bed66187d4e62bdb6bef，工作区有其他任务在修改，不能将该 SHA 当成无修改的构建指纹。\n- 主前端：独立 3310 固定构建 .codex-run/ui-audit-preview-20260906，构建日志 .codex-run/ui-audit-build.log；未用持续变化的3000开发页面作为全部证据基线。部分最早记录后来被稳定复核替代。\n- 后端：共用8000；账号 local。远端插件 iframe 资源由后端提供，未冻结。其他任务在走查中改变了角色、会话、模型和插件状态，截图中的时间/数量可能不同。\n- 视口：桌面1294×912、窄窗900×700、手机390×844；深色抽查设置、HUB、Design后恢复跟随系统。\n- 采用页面截图、DOM/可访问树及源码入口交叉核对。错误态只证明错误呈现，不代表其背后的功能通过。没有通过注入数据或绕过权限制造成功截图。\n- 未提交任务、公开分享、发布帖子、安装插件、创建订单、改权限或删除用户数据；草稿关闭。浏览器内为检查创建的空小组件已删除，只清理该自建条目。早期邀请入口曾自动准备群组房间，未生成或发送邀请。\n- 原生系统窗口无法由当前浏览器工具观察；屏幕阅读器、真实触屏/软键盘、精确对比度、所有语言和所有提交后状态未验证。\n\n截图状态统计：${Object.entries(counts).map(([k,v])=>`${k} ${v}`).join('；')}。已取证只表示当前状态有证据，不表示功能验收通过。\n\n## 按入口走查结果\n\n|序号|区域|实际检查|证据编号|边界|\n|---|---|---|---|---|\n`;
routes.forEach((r,i)=>md+=`|${i+1}|${r[0]} · ${r[1]}|${r[2]}|${r[3]}|${r[4]}|\n`);
md+='\n公开/旧入口的路由别名按源码归并：workspace/browser→browser，mobile→computer，mcp→工具设置，skills/plugins/store/workflows→HUB对应页，nas/database→storage，replay→observability。别名不是额外的独立窗口。根路径和未知路由属于重定向分支，仅源码归并，未逐个新增截图。\n\n## 优先整改\n\n';
for(const i of issues)md+=`### ${i.id} · ${i.priority} · ${i.title}\n\n**证据**：${i.evidence.map(mdLink).join('、')}。\n\n${i.observation}\n\n影响：${i.impact}\n\n建议：${i.recommendation}\n\n验收：${i.acceptance}\n\n`;
md+='## 三个代表现场\n\n';
for(const n of [132,224,315])md+=`### ${n} · ${evidence(n).area}\n\n![${h(evidence(n).name)}](${evidence(n).screenshot})\n\n${evidence(n).notes}\n\n`;
md+='## 建议实施顺序\n\n1. 修复 F01–F09：先让数据、状态、导航和错误恢复可信；用断网、403、502、空响应和部分步骤失败来验收。\n2. 收敛任务主流程：以对话、项目、产物、运行状态为主线；双引擎通过自动路由和可展开详情呈现，避免前置多个配置决定。\n3. 统一组件和词表：应用目录、能力状态、表单、弹层、空态、移动导航复用同一规范；保持已成熟的设置响应式方案。\n4. 补数据条件覆盖：使用独立测试账号和专用测试项目补查下表条件窗口，再开展真实桌面与屏幕阅读器验收。\n\n## 可以保留的设计\n\n- 分享前明确公开只读范围（259）；聊天删除确认包含目标名、默认焦点落在取消（282）。\n- 空设置搜索给出关键词建议（48），手机历史搜索有明确零结果（310）。\n- 项目计划和密钥轮换在必填为空时禁用提交（279、324）。\n- 900px 工作台转为抽屉，关闭恢复聊天；390px 设置改横向导航和单列正文（304–307）。\n- HUB分类/角色分页正常，深色主题在宿主与Design首页衔接（302–303、320–322）。\n\n## 源码窗口清单闭合情况\n\n下面逐个列出发现的窗口相关文件。源码未挂载和条件未验证都不计通过；基础组件采用代表调用验证，不声称穷尽所有调用状态。\n\n|文件|状态|依据与限制|证据|\n|---|---|---|---|\n';
sourceRows.forEach(r=>md+=`|${r.file}|${r.status}|${r.reason}|${r.evidence||'源码检索'}|\n`);
md+='\n补充条件：原生文件/文件夹选择、OAuth与云账号、付款成功、公开分享二维码、有效邀请接受、插件成功安装/升级/回滚、已有数据编辑删除、并行子任务详情、消息审批和多媒体预览均不在本轮成功流程证明范围内。设计工作台远端包的全部专用节点编辑器、叙事项目内部章节/分支，以及所有外部网站窗口没有伪造数据强行覆盖。\n\n## 全部编号记录\n\n';
rows.forEach(r=>md+=`${r.step}. **${r.area} / ${r.name}** — ${r.health}（${r.status}）${r.supersededBy?`；以 ${r.supersededBy} 为准`:''}。${r.notes} [截图](${r.screenshot}) · [DOM记录](${r.ax})\n\n`);
md+='## 文件\n\n- index.html：可搜索的截图与问题索引，直接本地打开，无外部资源。\n- coverage.json：编号、区域、状态、备注、截图及问题对应关系。\n- issues.csv / findings.json：24项合并问题、优先级及验收条件。\n- source-window-coverage.csv：逐源码文件的已查、受阻和条件说明。\n- window-source-inventory.txt：原始源码窗口检索清单。\n\n本轮只完成审查与报告，没有修改业务前端代码或宣称这些问题已修复。\n';
md+='\n## 报告自身校验\n\n326组PNG和DOM文件引用存在；PNG尺寸有效；生成脚本及HTML内脚本通过语法检查。HTML的本地浏览器打开被URL安全策略拒绝，未通过其他途径绕过，所以交互与最终HTML视觉呈现未验证；该限制不影响此前已取得的产品截图。独立3310审查预览服务已停止，未停止用户3000/8000服务。\n';
fs.writeFileSync(path.join(dir,'audit.md'),md);
const payload=JSON.stringify({rows,issues,sourceRows,counts,routes}).replaceAll('<','\\u003c');
const html=`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Echo · 全量前端走查</title><style>
*{box-sizing:border-box}body{margin:0;background:#f6f7f9;color:#1d2738;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}header{background:#13243b;color:#fff;padding:38px max(24px,calc((100vw - 1220px)/2))}h1{font-size:30px;margin:4px 0 12px}header p{max-width:980px;color:#d2ddea}a{color:#2468b8;text-underline-offset:3px}header a{color:#c4defe}.meta{font-size:13px;letter-spacing:.1em;color:#a9c7e7}main{max-width:1268px;margin:auto;padding:24px}nav{display:flex;gap:18px;flex-wrap:wrap}section{margin:30px 0}h2{font-size:22px;margin:0 0 16px}.stats{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0}.stat{background:#fff;border:1px solid #dbe1ea;padding:12px 20px;border-radius:12px}.stat b{font-size:24px;margin-right:8px}.filter{position:sticky;top:0;background:#f6f7f9f5;z-index:4;display:flex;gap:12px;padding:14px 0;flex-wrap:wrap}input,select,button{font:inherit;padding:10px 12px;border:1px solid #b8c4d5;border-radius:8px;background:#fff;color:inherit}input{flex:1;min-width:220px}button{cursor:pointer}button:focus-visible,input:focus-visible,select:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid #538fd5;outline-offset:3px}.issues{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}.issue,.shot{background:#fff;border:1px solid #dbe1ea;border-radius:12px;overflow:hidden}.issue{padding:18px}.issue h3{font-size:17px;margin:5px 0}.issue p{margin:10px 0}.badge{display:inline-block;border-radius:5px;padding:1px 7px;font-size:12px;background:#e8edf5;color:#40536d}.p1{background:#fce6e7;color:#9d242b}.p2{background:#fff0d4;color:#825712}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:18px}.shot img{display:block;width:100%;height:235px;object-fit:contain;background:#e9edf2}.shot .body{padding:16px}.shot h3{font-size:15px;margin:7px 0;overflow-wrap:anywhere}.shot p{font-size:13px;color:#45546c}.muted{color:#65738a;font-size:13px}.table{overflow:auto;background:#fff;border:1px solid #dbe1ea;border-radius:12px}table{width:100%;border-collapse:collapse;min-width:850px;font-size:13px}td,th{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #e1e6ee}th{background:#eaf0f7;position:sticky;top:0}td:first-child{overflow-wrap:anywhere;max-width:300px}details{margin:18px 0}summary{cursor:pointer;font-weight:600}#load{display:block;margin:24px auto}footer{color:#65738a;padding:30px 0}@media(max-width:600px){main{padding:16px}.grid{grid-template-columns:1fr}header{padding:28px 20px}h1{font-size:25px}.filter select{flex:1}.shot img{height:200px}}
</style><header><div class="meta">ECHO / FRONTEND AUDIT · 2026.09.06</div><h1>让状态可信，让操作有结果</h1><p>${h(summary)}</p><p>主页面、菜单、弹窗、抽屉、错误态、空态与响应式对照。当前可达路径已取证；原生能力、账号和数据条件窗口逐项列出边界。</p><nav><a href="audit.md">完整报告</a><a href="issues.csv">整改表 CSV</a><a href="source-window-coverage.csv">源码窗口清单 CSV</a><a href="#evidence">截图索引</a><a href="#coverage">范围与限制</a></nav></header><main><div class="stats"><div class="stat"><b>${rows.length}</b>编号记录</div><div class="stat"><b>${issues.length}</b>合并问题</div><div class="stat"><b>${sourceRows.length}</b>源码文件对照</div><div class="stat"><b>3</b>视口尺寸</div></div><p class="muted">“已取证”不等于“通过”。后端与远端工作台资源在走查中仍变化；未修改业务代码。截图包含本地会话内容，仅保存在本机。</p><section><h2>整改优先级</h2><div id="issues" class="issues"></div></section><section id="coverage"><h2>逐入口覆盖与未验证条件</h2><div class="table"><table><thead><tr><th>序号 / 区域</th><th>检查内容</th><th>截图编号</th><th>边界</th></tr></thead><tbody id="routes"></tbody></table></div><details><summary>展开 ${sourceRows.length} 个源码窗口文件的逐项分类</summary><div class="table"><table><thead><tr><th>源码文件</th><th>状态</th><th>依据与限制</th><th>证据</th></tr></thead><tbody id="sources"></tbody></table></div></details></section><section id="evidence"><h2>逐窗口截图记录</h2><div class="filter"><input id="q" aria-label="搜索截图" placeholder="搜索名称、问题、状态或编号…"><select id="area" aria-label="按区域筛选"><option value="">全部区域</option></select><select id="status" aria-label="按证据状态筛选"><option value="">全部状态</option></select><button id="clear">清除筛选</button></div><p id="count" role="status" class="muted"></p><div id="grid" class="grid"></div><button id="load">继续显示</button></section><footer>未验证：真实原生窗口、付款/公开发布、真实连接、需要已有数据的后续窗口、屏幕阅读器与真实触屏。全部限制见完整报告。\n本页无第三方脚本与远程图片。</footer></main><script type="application/json" id="data">${payload}</script><script>
const data=JSON.parse(document.getElementById('data').textContent);const el=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let limit=48;
el('issues').innerHTML=data.issues.map(i=>'<article class="issue"><span class="badge '+i.priority.toLowerCase()+'">'+i.priority+' · '+i.id+'</span><h3>'+esc(i.title)+'</h3><p>'+esc(i.observation)+'</p><p><b>建议：</b>'+esc(i.recommendation)+'</p><p class="muted">证据 '+i.evidence.map(n=>'<a href="#shot-'+n+'" data-step="'+n+'">'+n+'</a>').join(' · ')+'</p></article>').join('');
el('routes').innerHTML=data.routes.map((r,i)=>'<tr><td>'+String(i+1)+'. '+esc(r[0])+'<br><span class="muted">'+esc(r[1])+'</span></td><td>'+esc(r[2])+'</td><td>'+esc(r[3])+'</td><td>'+esc(r[4])+'</td></tr>').join('');
el('sources').innerHTML=data.sourceRows.map(r=>'<tr><td>'+esc(r.file)+'</td><td>'+esc(r.status)+'</td><td>'+esc(r.reason)+'</td><td>'+esc(r.evidence||'源码检索')+'</td></tr>').join('');
for(const area of new Set(data.rows.map(r=>r.area))){const o=document.createElement('option');o.value=o.textContent=area;el('area').append(o)}for(const status of Object.keys(data.counts)){const o=document.createElement('option');o.value=status;o.textContent=status+' ('+data.counts[status]+')';el('status').append(o)}
function render(){const q=el('q').value.trim().toLowerCase();const chosen=data.rows.filter(r=>(!el('area').value||r.area===el('area').value)&&(!el('status').value||r.status===el('status').value)&&(!q||[r.step,r.name,r.notes,r.area,r.status,...r.findings].join(' ').toLowerCase().includes(q)));el('count').textContent='匹配 '+chosen.length+' 条，显示 '+Math.min(limit,chosen.length)+' 条；点击截图查看原尺寸。';el('grid').innerHTML=chosen.slice(0,limit).map(r=>'<article class="shot" id="shot-'+r.step+'"><a href="'+esc(r.screenshot)+'" target="_blank" rel="noopener"><img loading="lazy" src="'+esc(r.screenshot)+'" alt="第'+r.step+'步 '+esc(r.area)+' '+esc(r.name)+'"></a><div class="body"><span class="badge">'+r.step+' · '+esc(r.status)+'</span><h3>'+esc(r.area)+' / '+esc(r.name)+'</h3><p>'+esc(r.notes)+'</p><p class="muted">'+esc(r.findings.join(' / ')||r.health)+(r.supersededBy?' · 以 '+r.supersededBy+' 为准':'')+'</p><a href="'+esc(r.ax)+'">DOM 记录</a></div></article>').join('');el('load').hidden=limit>=chosen.length}
for(const id of ['q','area','status'])el(id).addEventListener(id==='q'?'input':'change',()=>{limit=48;render()});el('clear').onclick=()=>{el('q').value=el('area').value=el('status').value='';limit=48;render()};el('load').onclick=()=>{limit+=48;render()};document.addEventListener('click',e=>{const a=e.target.closest('[data-step]');if(!a)return;e.preventDefault();el('q').value=el('area').value=el('status').value='';limit=data.rows.length;render();location.hash='shot-'+a.dataset.step;el('shot-'+a.dataset.step).scrollIntoView({block:'center'})});render();if(location.hash.startsWith('#shot-')){limit=data.rows.length;render();document.querySelector(location.hash)?.scrollIntoView()}
</script></html>`;
fs.writeFileSync(path.join(dir,'index.html'),html);
const missing=rows.flatMap(r=>[r.screenshot,r.ax]).filter(f=>!fs.existsSync(path.join(dir,f)));
if(missing.length)throw Error('缺少证据文件 '+missing.join(','));
if(issues.some(i=>i.evidence.some(n=>!evidence(n)||excluded.has(n))))throw Error('问题引用无效截图');
console.log(JSON.stringify({records:rows.length,issues:issues.length,sourceFiles:sourceRows.length,counts,missing:missing.length,reportBytes:fs.statSync(path.join(dir,'audit.md')).size}));
