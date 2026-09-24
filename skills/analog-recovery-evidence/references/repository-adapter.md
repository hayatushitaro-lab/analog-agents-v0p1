# analog-agents仓库与作用域连接适配

## 编排依赖绑定

主编排按[角色卡](../../analog-recovery/references/role-cards.md)解析 repo_root、Python 和本角色所需的技能段落。源码仓库、安装技能和运行环境可能不在同一路径；记录所选版本，检查 Python 实际 import 来源后才声称已接通。复制过来的 editable 环境可能仍指向旧仓库，不能仅凭目录存在判断独立可运行。

已有 scope_packet/wiki_packet 继续复用。原 post-sim.sh 的“最近 PSF”选择与 post_tool_use.py 的失败传播不能默认作为 recovery 门禁：显式绑定 run，并检查内部 checker 的结果。尚未修复的工具路径保留限制，不以外层退出 0 宣称证据有效。详见主编排角色卡；本适配不修改原正向仓库。

## 先用作用域连接，不用全文同名猜连接

```text
python scripts/scope_packet.py <静态IR.json> --occurrence <IR中的完整occurrence_id> --net node_name --out <新的局部包.json>
```

occurrence也接受唯一的instance_path。多份输入可能都有同一路径，此时必须用包含来源的完整id；重复路径不自动选第一项。subckt声明按实例所在artifact查找，并与该occurrence的child definition_ref交叉核对；比较输入的同名定义不是本输入的include库。来源内歧义或引用冲突报错。输出同definition的端接、参数字面值、源位置、明确端口绑定，以及其他definition的同名网。后者是误连提醒，不是连接。

`--out`直接写新的UTF-8 JSON，已存在文件会拒绝覆盖。stdout仍输出同一JSON，使用ASCII转义保留Unicode字符串，避免Python与PowerShell编码不同损坏中文路径；经JSON读取后路径保持原文。优先引用原生输出中的source.path和sha256，不另手填路径映射。

若occurrence状态不完整，仍输出局部definition连接，`local_only=true`且不输出边界绑定。不能把局部可用事实升级为完整层级已解析。工具不是新parser，也不认定器件工作区/有效倍率。局部包会带原IR哈希，作为证据附件引用。

### 具名端口与模型端序

局部包的 `named_terminals` 按 subckt 声明顺序绑定实参；D/G/S/B 等器件端名只来自显式准入的 `--terminal-contracts <json>`。格式为 `{"model_name":{"terminal_order":["D","G","S","B"],"source_refs":["来源文件及位置"]}}`；这只是结构示例，不是任意 MOS 的已确认端序。优先使用实际 subckt 声明，metadata 不能覆盖它。

输出同时保留 ordinal、actual_name、net_ref、resolved_net、terminal_source_refs；压缩模式仍保留各成员源位置。当前或祖先 occurrence 不完整时不输出可用的 resolved_net；未知 master 的 named_terminals 为空，不靠实例名推断角色。CLI 记录 IR 及端序文件的哈希，仍须独立核对端序来源内容。端序契约不授权尺寸换算，width_semantics 始终 UNKNOWN；原始 W/nf/m 不变。

逐位控制交接直接消费相关实例的named_terminals并引用该局部包；按实际目标集合建立质量检查。字段可读和工具valid不替代原夹具连接复核，也不证明代理没有遗漏控制目标。

### 起点与目标的成对取证

检查控制接入时可在上述命令追加 `--target-net <同一definition中的目标实际网名或net_ref>`。结果的 `target_context` 是目标端的同款局部包；从其中相关实例的 `named_terminals` 直接交接 formal/ordinal/actual，引用包内字段位置，不另编映射。跨层级目标先通过父作用域具名投影确定实际网，再按边界记录展开；同名不作绑定。

`connection_assessment.direct_local_net` 只比较该作用域的网身份。`shared_component_refs` 只列同时端接两个网的实例，具体 master、端子和参数仍在两端包中；可能是电阻、源、子电路或未知器件，不能据此短接或认定导通。无共享实例也不能排除多器件路径。此功能复用现有 IR，不是全局寻路器；`global_device_path` 与 `effective_control` 均为 NOT_EVALUATED。

每个目标的交接分开回答：①直接网络关系及投影引用；②经哪些器件关联、所需条件或尚未展开的边界；③是否有独立刺激、能否支持所问控制/测量结论。负结论必须限定已检查范围；缺层级/器件语义时记 UNKNOWN，不能将“未找到”写成“无作用”。对于局部事实已齐全的目标应给出有依据的结论，不以全部 UNKNOWN 代替取证。

## 同一工作区、同一 wiki 的续作

使用 repo 的 `.venv/Scripts/python.exe`。维护源、唯一 `wiki/index.yml`、`edges.jsonl` 和被索引目录均在当前 repo；必要证据留本工作区项目产物目录。外部原路径仅作来源记录，准入后按需迁入，保留原件/hash，以新 manifest 登记本地位置。不追随指向工作区外的链接，不整库复制。

```text
<repo-python> <evidence-skill>/scripts/wiki_packet.py --repo <repo> --query <问题关键词> --projects
<repo-python> <evidence-skill>/scripts/wiki_packet.py --repo <repo> --entry <project-id> --projects
<repo-python> <evidence-skill>/scripts/wiki_packet.py --repo <repo> --entry <project-id> --projects --document narrative --start-line 1 --line-count 80
```

默认接口仍只读四类领域条目；生产续作显式加 --projects。索引查询不读正文，默认最多8项；单条正文16KB上限，narrative/trajectory可按行选读（最多500行且16KB）。相邻边和 derived_from/supersedes_context 只返回候选，不加载关联正文或 WORK。缺文档明确 missing；索引不搜索正文 tags。旧关系值原样显示，不能据关系名自行断言当前结论。历史 confidence 非标准值不升级为 verified。

普通读取拒绝 deprecated；审查旧解释可加 --audit。严格盲测才传 --exclude；生产同线路续作不要排除本项目。排除词在读后检查，不能据此保证严格盲测隔离。

先核对项目ID、DUT来源/版本、作用域与条件，沿已有续作链接读取。未变且有依据的结论可继承，变更只重开受影响项；历史报告与来源丢失的案例仅作线索。typical_specs/sizing_anchors不是当前原始规格，反推不能补造作者意图。

## recovery 写回

使用 `<repo>/tools/recovery_wiki.py`，不调用原 archive-project（其 convergence=true 与占位 narrative 不适用）。先 prepare 到本次 WORK，再审查 changes.diff，按已有授权 apply。原 wiki_ops 的索引/关系/新增领域条目/弃用函数继续复用，原正向接口不变。详细请求格式见主 recovery 的 [wiki 写回接口](../../analog-recovery/references/wiki-writeback.md)。

同一范围续作指定既有 project_id，保留旧 convergence/result/设计轮数；新增 recovery 项目 convergence=false。summary.recovery 记录本次 partial/blocked/complete，trajectory 按 block 保留原 iterations 并追加 recovery_iterations；narrative 追加有日期的认识修订，正式 JSONL/六文件证据包留项目产物目录。报告完成从不代表设计收敛。

局部撤回保存旧 content、原 confidence、原因与证据，修订条目回到 unverified；整条无效才 deprecate。新经验使用原四类目录和 derived_from。工具只验证引用/hash/结构，不证明电气正确或复核独立性。原 consult 不自动过滤 deprecated，读者必须看 confidence 和修订范围。

apply 重复执行同一准备目录返回 no-op；prepare 后源证据或 wiki 改变则拒绝。单写者使用，原工具不遵循 recovery 锁；写入故障自动回滚，硬中断后先 inspect 再 recover 原准备目录。不删除被案例引用的 WORK 文件。新任务从原 index、案例修订及证据续读，不依赖旧聊天或外部工作区。
