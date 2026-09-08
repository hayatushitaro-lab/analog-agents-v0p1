# 雷区库(pitfalls)

OTA 设计反复踩过的坑。Step 1/Step 2 动手前扫一眼,Step 8 有新坑就往里加。

## 偏置类

- **尾源必须用电流镜偏置,不用 VB 电压源**:`VB=3.3-(Vov+|Vth_p|)` 对 Vth 极敏感(实测 Vth≈0.69V),电压源偏置尾电流会远超设计值;电流镜(IREF + diode 参考管 + M5 镜像)精确 Itail。folded-cascode 曾因电压源偏置尾源直接增益 -90dB 崩塌。

## 尺寸计算类

- **μCox 假设别拍脑袋**:3.3V 器件 μCox 比 1.8V/1V 大 2~3 倍(NMOS≈187u、PMOS≈62u),假设小了 W 会算成 44u~224u 异常大值。优先查 `references/device_params.md`。
- **gm/Id 反推 W 用平方律或 Phase 0 LUT,不用自造三段插值**:三段插值在 gm/Id=10~15 区间让 Vov 骤降、W 暴涨(数学错误)。gm/Id>15 只预警不硬算。
- **tsmcN65 器件 `w` 是单指宽,total = w × fingers**:设尺寸用 `w=1u` + `fingers=round(总宽/1u)`,别把总宽直接塞进 w(总宽会涨 fingers 倍)。
- **画 schematic 尺寸必须显式设置**:留默认 w=400n/l=380n(Wmin/Lmin 双最小)会触发 Virtuoso CMI-2440;idc 电流源也要设 dc 值。

## 结构/输入类

- **输入对类型决定 Vcm 范围**:PMOS 输入 → Vcm 低(近 VSS);NMOS 输入 → Vcm 高(近 VDD)。反了放大器不工作。
- **5T 增益低**:单级 ro 并联,理论上限 ~27dB,要 60dB+ 用 cascode/两级。
- **折叠式/套筒式 cascode 栅偏置(如 VB2)要留电压余量**:给太高折叠节点进线性区(如 folded VB2 用 1.4V 而不是 1.8V)。

## 仿真/工具类

- **spectre 21.1 的 `-param X=Y` CLI 是坏的**:会被当成第二个网表报 SPECTRE-132;参数 bake 进网表 `.param`。
- **`+preset=cx` 与 `-format psfascii` 不兼容**;AC/DC 小信号提速用 `+preset=lx`(冲突就去掉)。
- **save=allpub 会让 raw 体积爆炸**:模板已用 `save=selected` + 显式列表,别改回。
- **AC 结果是复数**:相位不能只取实部,PM 要从复数相位算。

## 2026-08-18 telescopic 轮新增
- **telescopic 偏置:VB2(cascode 栅)过低 → 输入对 Vds 不足进线性**:VB2=1.5 时 net_a≈0.49V、net_tail≈0.40V → 输入对 Vds=0.09V < Vdsat → Av 只有 44dB;VB2 提到 1.8 后 Vds→0.4V,Av 52.6dB。先查偏置再怪结构。
- **升 Itail 不解决 telescopic 增益/带宽瓶颈**:Itail 100→200uA,gm/Id 从 12.6 降到 6.3(强反型),gm 效率降,Av 反而 52.6→47dB,GBW 没动(输出级钳位)。
- **SPECTRE18.1 不支持 `+preset=lx`**(报 SPECTRE-129),去掉即可;SKILL 里"冲突则去掉"实测生效。
- **parse_margin 单位换算坑**:① spec.yml 首行被 BOM 污染→正则失配(用 utf-8-sig);② 单位匹配必须大小写敏感(MHz 会匹配到 m 毫)。
- **parse_margin OP region 读 DC 扫描终点(污染)**:dc1 扫描后 region 是数组,取 [-1] 是终点非工作点;必须从 op*.dc 单值文件读。
- **gmid_char PMOS LUT**:spectre 的 gm 报正幅值、ids 为负 → gmid 必须取 abs;过滤条件用 abs(ids)<1e-12。

## 2026-08-18 folded 换结构轮新增
- **folded cascode 单级增益上限 = 输入管本征增益 ~31dB(不是 53dB)**:折叠结构里输入管漏极 = cascode 漏极 = 折叠节点 = 输出,输入管 ro1 直接并联输出、未被 cascode 放大(对比 telescopic:输入管漏接 cascode 源,cascode 漏才是输出,ro1 被 gm·ro 放大)。增益 ≈ gm1·ro1 = NMOS 本征增益 ≈37(31dB, nch_33 L=380n 实测 gm_gds≈37)。要 40dB 需换 telescopic(53dB)/两级/增益自举,或输入管 L 拉到 ~1u 硬挤(牺牲 fT)。**folded 的卖点是摆幅大,不是增益高**。
- **低功耗 spec(Itail≤100u + GBW=50M + CL=2p)会把 telescopic 输入对逼到弱反型边界**:gm1=2π·GBW·CL=628uS、Id=Itail/2=50u → gm/Id=12.6,Vov≈0,tt 下输入对判 region=3(亚阈)。这是 spec 固有矛盾(功耗/带宽四角),不是调 W 能解决的——W 加大提 GBW 只会让输入对更深弱反型。接受并记录,或上报 architect 放宽功耗。
- **W1 实测需 LUT 预测 ×2**:LUT(W=1u/L=380n 单管表征)的 id_w 对 OTA 输入管(Vds≈0.28V、W=30u)偏乐观 ~50%(15.15u 预测 vs 30u 实测达标)。LUT 应补不同 Vds 假设或按结构回标系数,别把 LUT 当精确值。

## 仿真/工具类补充
- **run_remote.ps1 的 `-Host` 参数与 PowerShell 内置只读变量 `$Host` 冲突**(param 声明会报错,脚本跑不起来):参数名改 `-SshHost`。已修复。

## 2026-08-19 两级 Miller 轮新增(结构已建:topologies/two_stage_miller_ota.yml)
- **两级 Miller 第二级静态匹配(关键)**:M6 栅=第一级输出 net_a,被 PMOS 镜钳位 → |Vov6|=|Vov3|,M6 饱和电流 = Id1·(W6/L6)/(W3/L3)。**W6 不能按 gm/Id 查表自由定**——必须 W6=I6·W3·L6/(Id1·L3) 使 M6 饱和电流=I6,否则 M6 或 M7 必进 triode(v1:W6 过大→M6 深 triode,Av 只有 39.9dB;v2:失配 12%→M7 triode)。W6 计算后还需实测反推校准(平方律高估 ~13%)。
- **两级 Miller 的 p2 陷阱(65nm IO 物理限制)**:教科书 p2=gm6/(2π·CL)=86MHz 需 C1(第一级节点寄生,主成分 Cgs6)≈0。65nm IO 器件 W6 大 → Cgs6≈2.6pF 挂在 net_a → p2 退化为 1/(2π·R2·(CL+Cc'))≈0.32MHz(R2=ro6‖ro7≈138k)。**要 PM≥60° 需 p2≥2.2·GBW,而 p2 受 (R2 撑增益 vs CL=2p) 约束,GBW=50MHz 时不可达**。减 W6→p2 上限仅 ~14MHz;减 R2→A2 崩;升 I6→功耗爆。实测:Av=86.4dB ✓ / GBW=35.5MHz(受 p2 拖累)/ PM=-148° ✗ / Itotal=195u ✓。**结论:Av≥70/GBW≥50M/PM≥60°/CL=2p/Itail≤200u 五项同时不可达,需降指标或换结构(如 GBW 降到 ~5MHz 或第三级/增益自举)**。
- **两级 Miller 功耗分配**:总预算 IREF 5% / 第一级 30% / 第二级 60%(第二级电流是 PM 旋钮);设计留 ~5% 裕量(沟道调制实测 +5%,v1 设计 200u 实测 207u 超)。
- **偏置去耦**:第二级电流源 M7 栅与尾源共享 nbias(Mbias diode 阻抗 ~10.8k,非理想偏置)→ 建议 nbias 挂 AC 去耦电容(未验证,待下一轮)。

## 2026-08-19 schematic 版验证轮新增(case:two_stage_miller_ota_35m_sch)
- **Virtuoso 画第二级 CS 管 L 必须按设计值(380n),画成 1u 会让负载管出饱和、增益崩 40dB**:用户手画版 MM5(=M8)的 L 误设 1u(v7=380n)→ W/L 33 vs 86.8,M8 电流能力只剩 38%,供不出 M9(镜像 ~110u)要拉的电流 → **M9 被顶出饱和(region=1 弱反型)**、gm 0.21m。实测:Av 39.7dB(差 30dB)/ GBW 0.83MHz / Itotal 45uA(异常小,第二级电流崩)。仅改 MM5 L→380n 全达标(80.1dB / 3.74MHz / 85.8° / 162uA)。
- **不饱和的往往是负载管,不是 CS 管**:此案例里 MM5(CS)region=2 反而正常,是 MM6(负载)region=1。判定第二级健康**必须同时看两只管的 region + vout 静态中置**,别只看 CS 管。
- **画图转网表参数核对清单**:每个管对 v7 的 L/W(总宽=w×m)逐项比,重点 L——W 错了只是性能偏移,L 错可能静态失衡。schematic 版管号与脚本版不同(MM5=M8、MM6=M9),**按节点对应,勿按管号**。
- **运放 AC 验收起扫用 1Hz,Av 取 1–100Hz 平台**:两级 Miller 主极点 ~350Hz,1kHz 已在滚降区,读数比真实增益低 ~9dB(70.9 vs 80.1)。spec 若写"Av@1kHz"是保守口径;真实增益看平台。

## 2026-08-20 全差分 CMFB 轮新增(case:fully_diff_cmfb_ota_17m,结构已建:topologies/fully_diff_cmfb_ota.yml)
- **全差分 telescopic 第一级输出是高阻无反馈节点**:net_ap/an 是 PMOS 负载电流源 vs NMOS cascode 电流源对顶,静态电流镜 ±4% 失配就会把它推到轨(v6:3.2V 上轨 / v7:0.16V 下轨),第二级随之深度导通、Itotal 爆炸数十倍(1.94mA~10.6mA)。**根治:给第一级加 CMFB 环路钳 net_ap/an 共模(v8),不要靠静态镜像匹配/反复调 W**。v3~v7 调 W5/Wb5d 五轮无解,加第一级 CMFB 一轮根治。
- **第一级 CMFB 输入共模高(VCM1≈2.2V)→ 必须 NMOS 输入对 + PMOS 镜负载**:PMOS 输入对会重蹈"尾源电平低于栅→全关断"坑(v1 教训的镜像)。
- **CMFB 尾源是独立 VDD→VSS 支路,不能按"镜像参考管不额外计电"忽略**:输出 CMFB 尾源 Mcm5 从 VDD 单独抽电(v2~v11 都漏算 → Itotal 实际 206 vs 预算 200);双 CMFB 时每环路的尾源都要独立计入功耗预算。
- **两级 Miller GBW 受 p2 物理约束(全差分同款)**:GBW=20MHz + PM≥60° + Itotal≤200uA + CL=2p 在 65nm IO 不可达——p2=gm8/(2π·CL),gm8 受限;实测极限 ~17.2MHz(architect 决策降标至 17MHz 达标)。GBW 差的量全部来自 p2 拖前效应(理论 20.5 vs 实测 17.2,p2=40.7MHz 仅 2.36×GBW)。
- **第一级感测电阻 RS1 必须 ≥10×Rout1(全差分第一级 Rout1≈1.09M,RS1 需 3M)**:v8 用 200k → Ad1 从 46dB 掉到 29.8dB,Av 缺 3.3dB。
- **第二级 CS 管 W8 的 |Vov8| 由 VCM1 决定**:|Vov8|=(VDD−VCM1)−|Vth_p|;v8 初版公式把 vov8_est 错误 clamp 到 0.15 → W8=38u 过大 → 第二级 937uA/侧;VCM1=2.5V 时正确值 0.227V。
- **全差分输出 CMFB 参考电压必须有独立 vsource**:VCM_OUT=1.65 只写 parameters 不接电源 → Mcmn 参考栅实际 0V → 输出共模被钳错位(v2 实测 0.965V)。
- **parse_margin.py 差分输出**:全差分用 vout_p−vout_n,parse_margin.py 已支持(analyze_ac 检测 vout_p/vout_n);AC 低频相位两级差分链为同相 ≈0°(不是单端两级 −180°),PM=180+phase 直接算。
