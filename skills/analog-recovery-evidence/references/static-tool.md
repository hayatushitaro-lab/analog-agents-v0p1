# 随包静态工具

`scripts/static_cli.py` 是既有 MVP-A 解析器的固定快照入口，默认 SCS 主源，CDL 可选；不执行模型或仿真。

```text
python scripts/static_cli.py run --manifest input.json --root <项目根> --output <项目根下新目录>
python scripts/static_cli.py validate --manifest input.json --root <项目根> --evidence <静态IR路径>
```

manifest 使用原 MVP-A 格式，见 `schemas/static-manifest-example.json`。准入 exact files 和 SHA256，不自动递归读取 include。
先生成用户授权输入的清单与哈希再运行，不把示例中的文件名视为真实来源。

支持已有 Spectre 子集的 subckt/实例/有序端口/续行、字面参数和部分确定性表达式、层级绑定及位置引用；CDL 仅辅助比较。
不是完整 Spectre/HSPICE 语言实现。预处理、复杂语言切换、模型执行、动态配置、全方言表达式语义不能据此声称已解析。
检查 acceptance/diagnostics 和结构覆盖，不能因为退出码为零就把 UNKNOWN 语义写成事实。未准入依赖先记录再按用户授权确认。
该静态 IR 与报告交接包独立，作为 manifest artifact 被报告证据引用；不强迫静态解析器生成电气角色或设计意图。
