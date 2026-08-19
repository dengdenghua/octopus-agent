# 数位分身(Digital Twins)

> 一批**「AI 还不能完全替代的真人岗位」数位分身** —— 每个对应一个真人岗位,
> 形态是「真人岗位接口 + AI 办公代理 + 长期记忆」:AI 能做的自动闭环,
> 物理动作 / 真人责任 / 商务决策交给真人,绝不伪造结果。

## 与 100 个数字分身岗位模板的关系

- **100 个岗位模板**(`octopus-enterprise/backend/app/agent_assets/twins_data.json`)
  是轻量声明式清单(岗位名 + 职责一行)。
- 本目录把这其中**需要真身协同**的硬件实体岗位单独整理成
  `hardware-physical-collab.json`(40 核心 + 20 扩展)。
- **`agents/twin_*` 是把「AI 不可替代真人岗位」落地成可运行的 octopus 数位分身**
  (带授权边界 + 真身协同协议 + 交接包),可直接在 Hub 使用。

## 已生成数位分身(31 个)

### 🔧 研发制造类(AI 替代不了真实硬件/产线验证)
| agent id | 名称 | AI 替代不了的边界 |
|---|---|---|
| `twin_hw_engineer` | 硬件工程师分身 | 打样打板/贴片/上电实测/EMC 整改 |
| `twin_electronics` | 电子工程师分身 | 器件实测/波形验证/电路调试 |
| `twin_embedded` | 嵌入式工程师分身 | 上板烧录/功耗时序实测/联调 |
| `twin_structural_engineer` | 结构工程师分身 | 开模/手板/装配验证/签样 |
| `twin_industrial_design` | 工业设计师分身 | 手板评审/CMF 定版/外观签样 |
| `twin_optical` | 光学工程师分身 | 光学装调/测试实测/送样确认 |
| `twin_rf` | 射频工程师分身 | 暗室实测/天线测试/认证送测 |
| `twin_cae` | CAE 仿真工程师分身 | 仿真与实测对比/模型校验 |
| `twin_process` | 工艺工程师分身 | 现场调机/首件确认/工艺放行 |
| `twin_npi` | NPI 量产导入分身 | 试产放行/停线决策/量产变更 |
| `twin_manufacturing` | 生产制造工程师分身 | 产线调机/试产放行/良率实测 |
| `twin_reliability` | 可靠性工程师分身 | 老化/跌落/环境实测/失效判定 |
| `twin_quality` | 质量工程师分身 | 现场验货/FAI/签样/8D 正式发出 |
| `twin_fae` | FAE 应用工程师分身 | 现场调试/客户承诺/问题升级 |

### 🚚 供应链 / 经营 / 项目
| agent id | 名称 | AI 替代不了的边界 |
|---|---|---|
| `twin_supply_chain` | 供应链与采购分身 | 议价/成交/供应商关系/付款 |
| `twin_operations` | 运营管理分身 | 现场管理/客户投诉处置/经营决策 |
| `twin_project` | 项目经理分身 | 排期裁决/跨部门推动/交期承诺 |
| `twin_hw_product` | 硬件产品经理分身 | 产品取舍/打样变更/对外承诺 |
| `twin_product` | 产品经理分身 | 需求取舍/版本范围/对外承诺 |
| `twin_founder` | 创始人/CEO 分身 | 战略/融资/重大支出/对外承诺 |

### ⚖️ 专业服务类(真人责任不可替代)
| agent id | 名称 | AI 替代不了的边界 |
|---|---|---|
| `twin_legal` | 法务合规分身 | 签字盖章/法律意见/责任承担 |
| `twin_lawyer` | 律师分身 | 出庭/代理/签字/执业责任 |
| `twin_finance` | 财务分身 | 审批付款/对外披露/账期承诺 |
| `twin_audit` | 审计分身 | 现场审计/函证/签字/鉴证责任 |
| `twin_tax` | 税务分身 | 正式申报/筹划决策/税务责任 |
| `twin_investment` | 投融资分析师分身 | 估值/投资决策/尽调判断/签约 |
| `twin_hr` | 人力资源分身 | 录用/offer/人事评价/辞退 |
| `twin_sales` | 销售与商务分身 | 报价/谈判/签约/客户关系 |
| `twin_health` | 医疗健康协作分身 | 诊断/处方/治疗方案必须真人医生 |
| `twin_nurse` | 护理协作分身 | 实际护理操作/患者处置必须真人护士 |
| `twin_psychology` | 心理咨询师分身 | 诊断/干预/危机处置必须真人咨询师 |

每个分身 `profile.jsonc` 带 `capabilities: { digital_twin, human_collab,
authorization_boundary, handoff_pack }`,`agent-core/AGENTS.md` 内置
**真身协同协议**(auto / need_human_confirm / forbidden + 交接包模板)。

## 结构

```
extensions/digital-twins/
├── README.md                        # 本文件
├── hardware-physical-collab.json    # 硬件实体协同岗位清单(40 核心 + 20 扩展)
├── spec/
│   └── digital-twin-spec.md         # 数位分身规范(授权边界/真身协同/交接包)
├── scaffold_human_twins.py          # 数位分身生成器(可一键扩展更多岗位)
└── (输出) agents/twin_*             # 生成的 octopus 数位分身
```

## 生成 / 扩展

```bash
# 重新生成全部 31 个
python3 extensions/digital-twins/scaffold_human_twins.py
# 只生成指定岗位
python3 extensions/digital-twins/scaffold_human_twins.py --only hw_engineer,structural_engineer
```

新增岗位:在 `scaffold_human_twins.py` 的 `HUMAN_TWINS` 列表里加一个 dict
(slug/name/role/profession/mission/ai_can/need_confirm/forbidden/knowledge)
再运行脚本即可。

## 数位分身 vs 普通专家

- **普通专家 agent**:独立第三方,尽量自己产出全部结果。
- **数位分身 twin**:代表真人岗位,设计与文档侧闭环,**物理动作与真人责任决策
  必须回传真人**,用「交接包」把待办交出去,等回传再继续,禁止伪造实测/进度。
