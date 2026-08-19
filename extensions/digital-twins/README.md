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
- **已全量铺开**:100 个岗位模板 + 11 个额外真人岗位(销售/FAE/工艺/医疗/护理/
  律师/审计/税务/投融资/心理/运营)= **111 个数位分身**。

## 已生成数位分身(111 个)

### 一、手工精写(31 个,质量最高,建议优先使用)

#### 🔧 研发制造类(AI 替代不了真实硬件/产线验证)
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

#### 🚚 供应链 / 经营 / 项目
| agent id | 名称 | AI 替代不了的边界 |
|---|---|---|
| `twin_supply_chain` | 供应链与采购分身 | 议价/成交/供应商关系/付款 |
| `twin_operations` | 运营管理分身 | 现场管理/客户投诉处置/经营决策 |
| `twin_project` | 项目经理分身 | 排期裁决/跨部门推动/交期承诺 |
| `twin_hw_product` | 硬件产品经理分身 | 产品取舍/打样变更/对外承诺 |
| `twin_product` | 产品经理分身 | 需求取舍/版本范围/对外承诺 |
| `twin_founder` | 创始人/CEO 分身 | 战略/融资/重大支出/对外承诺 |

#### ⚖️ 专业服务类(真人责任不可替代)
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

### 二、模板自动生成(80 个,由 100 岗位模板按 9 组自动展开)

#### 经营 / 产品 / 项目岗(5)
- `twin_business_assistant` 经营助理 / 总经理助理
- `twin_ai_product_manager` AI 产品经理
- `twin_user_researcher` 用户研究员
- `twin_technical_program_manager` 技术项目经理 / TPM
- `twin_pmo_manager` PMO 经理

#### 电子 / 电气 / PCB / 电源岗(12)
- `twin_electrical_engineer` 电气工程师
- `twin_pcb_engineer` PCB 工程师
- `twin_pcb_layout_engineer` PCB Layout 工程师
- `twin_power_engineer` 电源工程师
- `twin_battery_engineer` 电池工程师
- `twin_connector_engineer` 连接器工程师
- `twin_signal_integrity_engineer` 信号完整性工程师 / SI
- `twin_power_integrity_engineer` 电源完整性工程师 / PI
- `twin_emc_emi_engineer` EMC/EMI 工程师
- `twin_hardware_system_engineer` 硬件系统工程师
- `twin_hardware_test_engineer` 硬件测试工程师
- `twin_hardware_technician` 硬件技术员

#### 光 / 光机 / 显示 / 传感岗(11)
- `twin_opto_mechanical_engineer` 光机工程师
- `twin_display_engineer` 显示工程师
- `twin_camera_engineer` 摄像头工程师
- `twin_vision_engineer` 视觉工程师
- `twin_image_quality_engineer` 图像质量工程师 / IQ Engineer
- `twin_sensor_engineer` 传感器工程师
- `twin_touch_engineer` 触控工程师
- `twin_lidar_tof_engineer` 激光/雷达工程师
- `twin_optoelectronic_engineer` 光电工程师
- `twin_infrared_engineer` 红外工程师
- `twin_display_test_engineer` 显示测试工程师

#### 射频 / 通信 / 天线岗(7)
- `twin_antenna_engineer` 天线工程师
- `twin_wireless_communication_engineer` 无线通信工程师
- `twin_bluetooth_engineer` 蓝牙工程师
- `twin_wifi_engineer` Wi-Fi 工程师
- `twin_cellular_engineer` 蜂窝通信工程师
- `twin_gnss_gps_engineer` GNSS/GPS 工程师
- `twin_communication_protocol_engineer` 通信协议工程师

#### 机械 / 结构 / 工业设计 / 包装岗(9)
- `twin_mechanical_engineer` 机械工程师
- `twin_product_design_engineer` 产品设计工程师
- `twin_cmf_designer` CMF 设计师
- `twin_packaging_engineer` 包装工程师
- `twin_materials_engineer` 材料工程师
- `twin_tooling_engineer` 模具工程师
- `twin_injection_molding_engineer` 注塑工程师
- `twin_sheet_metal_engineer` 钣金工程师
- `twin_prototype_engineer` 样机工程师 / Prototype Engineer

#### 热 / 声 / 可靠性 / 测试岗(9)
- `twin_thermal_design_engineer` 热设计工程师
- `twin_thermal_simulation_engineer` 热仿真工程师
- `twin_thermal_test_engineer` 热测试工程师
- `twin_acoustic_engineer` 声学工程师
- `twin_audio_engineer` 音频工程师
- `twin_vibration_engineer` 振动工程师
- `twin_test_engineer` 测试工程师
- `twin_failure_analysis_engineer` 失效分析工程师 / FA
- `twin_product_integrity_engineer` 产品完整性工程师

#### 嵌入式 / 固件 / 软件 / 算法岗(7)
- `twin_firmware_engineer` 固件工程师
- `twin_bsp_engineer` BSP 工程师
- `twin_linux_driver_engineer` Linux 驱动工程师
- `twin_android_system_engineer` Android 系统工程师
- `twin_ai_engineer` AI 工程师
- `twin_algorithm_engineer` 算法工程师
- `twin_machine_vision_algorithm_engineer` 机器视觉算法工程师

#### 制造 / 质量 / 供应链岗(1)
- `twin_procurement_manager_buyer` 采购经理 / Buyer

#### 复合专家岗(19)
- `twin_opto_mechanical_system_expert` 光机系统专家
- `twin_mechatronics_expert` 机电一体化专家
- `twin_thermal_structure_expert` 热-结构联合专家
- `twin_acoustic_structure_expert` 声学-结构专家
- `twin_rf_structure_expert` 射频-结构专家
- `twin_power_thermal_expert` 电源-热专家
- `twin_hardware_system_architect` 硬件系统架构专家
- `twin_embedded_hardware_debug_expert` 嵌入式-硬件联调专家
- `twin_robotics_system_expert` 机器人系统专家
- `twin_smart_hardware_product_architect` 智能硬件产品架构专家
- `twin_dfm_dfx_expert` DFM/DFx 专家
- `twin_supply_chain_engineering_expert` 供应链工程专家
- `twin_supplier_quality_expert` 供应商质量专家
- `twin_hardware_quality_closed_loop_expert` 硬件质量闭环专家
- `twin_product_compliance_certification_expert` 产品合规认证专家
- `twin_factory_delivery_expert` 工厂交付专家
- `twin_ai_hardware_system_expert` AI 硬件系统专家
- `twin_smart_manufacturing_automation_expert` 智能制造自动化专家
- `twin_presales_solution_expert` 售前解决方案专家

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
├── scaffold_human_twins.py          # 数位分身生成器(手工 31 + 模板 100 全量铺开)
└── (输出) agents/twin_*             # 生成的 octopus 数位分身(111 个)
```

## 生成 / 扩展

```bash
# 全量生成(手工 31 + twins_data.json 模板自动铺开 80 = 111)
python3 extensions/digital-twins/scaffold_human_twins.py
# 只生成指定岗位
python3 extensions/digital-twins/scaffold_human_twins.py --only hw_engineer,structural_engineer
# 指定模板源(默认自动探测上游 octopus-enterprise)
python3 extensions/digital-twins/scaffold_human_twins.py --source /path/to/twins_data.json
```

**新增/精写岗位**:在 `scaffold_human_twins.py` 的 `HUMAN_TWINS` 列表加一个 dict
(slug/name/role/profession/mission/ai_can/need_confirm/forbidden/knowledge)
再运行脚本;如该岗位在 100 模板内,记得同时补一行 `SOURCE_ROLE_COVERAGE` 映射,
避免重复生成。

## 数位分身 vs 普通专家

- **普通专家 agent**:独立第三方,尽量自己产出全部结果。
- **数位分身 twin**:代表真人岗位,设计与文档侧闭环,**物理动作与真人责任决策
  必须回传真人**,用「交接包」把待办交出去,等回传再继续,禁止伪造实测/进度。
