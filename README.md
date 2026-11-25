# 可持续披露文本的来源复用与访查选样

业务交接资料为 UTF-8 JSON，每个文件保存一组记录。全部人名、机构、材料与项目均为虚构。
编号在各自资料中使用。保留原文中的省略、转述、标点和异体字，空字段表示交接中没有填值。

## 交接资料

- `data/texts.json` 保存id、主体、年度、类别、发布、收到、文字。披露、园区范文和采访纪要的原文及来源。披露主体使用 actors 中的登记编号。收到与发布采用同一格式的日期。

- `data/actors.json` 保存id、名称、场址、行业、集团、可接待。企业、场址、行业和集团归属。集团发稿不必是具体行动的所在地。

- `data/research.json` 保存id、原文。研究所制定的访查范围和提升覆盖优先规则。

- `data/visits.json` 保存id、日期、场址、人员、状态、目标。开放窗口和已确认、已执行的预约。文本目标与原访查资料并列保存。

## 阅读与运行

使用 Python 3.11.2 和标准库。在仓库根目录查看资料目录和一条原始记录。测试检查原文读入及资料关系。

```text
python3 -m corpus
python3 -m corpus texts --id T2
python3 -m unittest discover -s tests -v
```

## 来源复用与访查选样工具（`sourcing` 包）

仅用标准库，按"先分清文字从哪里来，再安排有限访查"的顺序组织：

- `textmodel`：保留原文切句切段，归一化后计算字符/二元组相似度，对齐出固定文字骨架与被替换的槽位。
- `provenance`：把段间关系分为范文复用 `template_reuse`、引用 `citation`、同一项目 `same_project`、仅文字照抄 `text_only_reuse`、仅术语共享 `shared_terms`；状态分 `proposed/confirmed/refuted`。同源只在能解释重复内容或同一项目的同类已确认边之间传递，通用范文边不会把两个独立项目连成一家。
- `claims`：同一段可拆开认定，模板承诺与引用同行不算本场行动，自写措施单独成为候选；状态区分文字所称 `text_claimed`、采访核实 `interview_verified`、现场核实 `site_verified` 与来源待区分 `source_pending`。
- `visits`：先保已确认/已完成且仍可核实的预约，再按研究格子以最早开放窗口补缺口，遵守每轮三次、同集团两个场址、只安排可接待工厂等约束；同场址补证并入已有预约，不占其他企业名额。
- `workspace`：接入更早范文或新采访后再规划。已完成访查保留实际场址与所核范围，未出发计划按新证据调整，并记录覆盖缺口变化。

常用命令：

```text
python3 -m sourcing links                       # 全部句段关系
python3 -m sourcing links --kind template_reuse # 只看范文复用
python3 -m sourcing alternatives T9-1-1         # 未证实同源的两种解释
python3 -m sourcing claims --site 北站           # 某场址行动候选
python3 -m sourcing plan                        # 访查选样、覆盖与余量
python3 -m sourcing explain T1-2-1 T2-2-1 --kind same_project
python3 -m sourcing revise --interview tests/fixtures/new_interview.json
python3 -m sourcing export -o reports/grouping.json
```

导出的分组材料可从每个访查对象回溯到互相重复的原段、独立自写内容、来源确认状态，并分清文字所称与采访/现场核实的事实。放不进本轮的候选按"来源待区分 / 同一行动已有覆盖 / 独立但没有合适窗口 / 无法接触"说明原因。

