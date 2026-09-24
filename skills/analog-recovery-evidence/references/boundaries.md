# 模式边界与计量契约 v0.2

用于制定验证计划、解释异常或复核夹具时。固定DUT，借鉴已有仿真/审查技能的执行能力，不继承正向调参循环。

## 先画清边界，再解释数字

- 以被报告模块为方向参照。上游输出可同时是下游输入；同名不证明角色，不同名也不证明断路。
- 沿器件端接追踪偏置入口到内部控制节点，允许电流镜、开关与反馈中转。不要要求所有路径共用网名。
- 参考节点可能既受外部驱动，又连接内部有源支路或关闭态钳位。把“没有看到理想源”写成“没有内部参考”是不成立的。
- 对疑似双向/共享节点，区分高阻观测、有限阻抗驱动与真实上游电路。强制某电压是诊断条件，不能据此证明该节点本来就是输入或本来具有该值。
- 独立模块与集成结果分别建指标；DC工作点、有限瞬态末值和稳态不要混同。由DC初始化的无扰动保持不能证明启动或稳定性。

## 最小可区分实验

解析器返回 opaque/unresolved，只表示工具尚未绑定语义，不能直接证明电路语义未知。先区分已确认方言的内建原语与需要外部定义的模型/子电路；通过适用的语言定义核对前者，通过准入依赖核对后者，不凭实例前缀猜测。能够写明假设的电路关系可登记为条件性推导，例如理想无负载的分压关系；不得冒充实际工作点。缺少原始规格不妨碍采用显式工程测试条件，也不妨碍列出能力范围，只有产品合格判定必须另有判据。

先写竞争解释及能区分它们的一项观测，再选择对照。只改变一个可说明的边界条件，保留原夹具和首次结果。仿真与预期不同时先查参考、偏置、控制、负载、版本和数值条件，不改DUT凑目标。

运行前记录源的输出阻抗/合规范围，运行后检查其实际电压、电流及模型适用范围。模型端电压、收敛或gmin警告需要解释；exit=0不代表无条件有效。相关数值做有界敏感性检查，无关警告留痕后继续交付。

关闭模式应明确哪些源仍在。分别列DUT供电、电流注入与源功率，说明计量参考平面。不同电压域的电流不能直接相加当总功耗；同一来源不要在供电端和注入端重复计算。

原始save项无效时，不能称已测得该支路电流。只有保存量足以按明确方程重算时才登记DERIVED；否则补测或UNKNOWN。公式及输入引用随结果交接。

## verification_contract.json

独立于0.1 evidence schema，避免破坏历史包。新仿真任务在执行前登记计划，执行后另存结果版；不覆盖计划。无仿真任务可不建立它，但不能宣称完成仿真门禁。

```json
{
  "version":"0.2", "scope":"standalone", "budget_s":120, "max_parallel":1,
  "boundary":[{"port":"ref","state":"driven","source":"有限阻抗诊断源；参数见deck","compliance":"电压/电流合规范围见已批准夹具","role_basis":"端接证据ID"}],
  "measurements":[{"id":"supply_current","quantity":"current","definition":"供电源正注入电流","domain":"supply_A","source_terms":["I_supply"],"excludes":["其他电源域"],"classification":"SIMULATED","method":""}],
  "runs":[{"id":"case_1","analysis":"dc","claim_scope":"operating_point","status":"planned","exit_code":null,"completed":false,"runtime_s":null,"warnings":[],"limitations":[],"saved_signals":[],"required_signals":["I_supply"],"derived_signals":[]}],
  "clarification":{"blocking":[],"assumptions":["当前条件仅为诊断，不是原始规格"]}
}
```

枚举：scope为standalone/integrated；state为driven/observed/disconnected；quantity为voltage/current/power/other；classification为SIMULATED/DERIVED；analysis为dc/hold/startup/other；claim_scope为operating_point/hold_only/startup/other；status为planned/valid/qualified/failed。

实际运行填原始日志中的完成状态、退出码、累计墙钟时间（包括初始化，失败也计费）；warnings逐条摘要，qualified必须给limitations。无法确定用保守上界并注明来源，不拿单个analysis耗时代替进程总耗时。实际并发仍由执行器记录，本检查器不从声明推断并发是否守约。

derived_signals为`{name, method, inputs:[已保存或可推导信号名]}`；只接受可解析依赖链，不接受循环或无输入推导。失败/未完成运行不得用于有效仿真指标。

执行 `python scripts/check_protocol.py verification_contract.json`，并运行原`check_bundle.py`检查证据引用与覆盖。协议只是声明检查，原始端接、方程正确性、日志真实性仍需独立复核。报告中的产品通过结论必须另有规格依据。
