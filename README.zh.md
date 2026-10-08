# skstate：用一份文书接管宿主

## 从零到 setup

```bash
# 1. 检出本仓库后，把仓库根设为 PYTHONPATH
export PYTHONPATH=/path/to/hermes-agent     # Windows PowerShell: $env:PYTHONPATH="C:\path\to\hermes-agent"

# 2. 只装 skstate 的依赖（mcp + PyYAML，不含 Hermes 的对话依赖）
pip install -r requirements-skstate.txt

# 3. 在你的项目根接入 IDE
cd /path/to/your/project
python -m skstate setup --platform opencode     # 或 --platform codex
python -m skstate status                        # 看懂接没接上
python -m skstate doctor                        # 排查安装问题
```

重启 IDE 后，新会话的第一条消息给出具体任务即可。没有技能也能跑（内置 `scratch` 规程）；要演示就加 `--example` 拿到 `shelf-demo`。

`skstate` 是这个仓库里的独立 MCP 运行时。它不导入 Hermes，也不调用 LLM API。宿主 Agent（OpenCode、Codex，或任何接了这个 MCP 服务的客户端）是唯一的语言模型。

连接建立时，MCP 的 `instructions` 就是接管文书。`skstate_boot` 返回的 `instrument_prompt`、名为 `skstate_instrument` 的 MCP prompt、以及 Codex 会话开始时注入的 additional context，都是同一份文书。宿主按这份文书工作：用户当前这条消息是任务，执行状态只认规程、结构化状态和最新观察。

英文总览在 [README.md](README.md)。仓库里的 `hermes` 对话、gateway 仍会自己请求模型，供本机 TUI 和消息平台使用。`hermes mcp serve` 仍是消息桥。那两条路径和 `skstate` 互不加载。

长程技能如果把每一步都追加进对话，提示会随步数变长。skstate 把执行收成三样东西，对应论文 SKILL.state（arXiv:2608.26263）：

- **规程 P**：选中的技能正文，运行期间不改。
- **状态 Σ**：一份结构化对象。模型提交补丁，运行时校验后合并。值为 `null` 的键会被删除。嵌套对象合并，数组和标量整段替换。
- **最新观察 O**：只保留上一次执行结果。

用户任务写在 run 的 `task` 字段上，不写进 Σ。推理留在宿主这一侧，不进入工具参数。schema 拒绝的补丁不会落盘。宿主用自己的终端、文件和网络工具执行 `action`。

## 启动

skstate 自己只需要 `mcp`（`mcp>=1.2,<2`）和 PyYAML。轻装方式就是上面「从零到 setup」的 `requirements-skstate.txt`。也可以在本仓库里整体安装（会带上 Hermes 的对话依赖）：

```bash
pip install -e ".[mcp]"
skstate
```

未安装控制台脚本时：

```bash
python -m skstate
python -m skstate serve
```

服务走 stdio。日志在 stderr。

### OpenCode

v1 把服务器直接放在 `mcp` 下。v2 放在 `mcp.servers` 下。

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "skstate": {
      "type": "local",
      "command": ["skstate"],
      "enabled": true
    }
  }
}
```

v2：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "skstate": {
        "type": "local",
        "command": ["skstate"],
        "enabled": true
      }
    }
  }
}
```

检出目录里如果还没有 `skstate` 命令，把 `command` 换成 `["python", "-m", "skstate"]`。

### Codex

```toml
[mcp_servers.skstate]
command = "skstate"
args = []
```

## 会话钩子

在目标项目根目录执行。安装只写到 `--project-dir`（默认当前目录），不会落到用户主目录。一条 `skstate setup --platform opencode|codex` 会同时写好 MCP 配置、会话钩子和 `.skstate/` 的 gitignore 规则；`skstate setup --platform ... --uninstall` 只移除这些标记过的条目。`skstate status` 用中文摘要说明当前接没接上。

```bash
skstate hooks --platform opencode
skstate hooks --platform codex
skstate hooks --platform codex --uninstall
```

OpenCode 插件同时写到 `.opencode/plugin/skstate.js` 和 `.opencode/plugins/skstate.js`。会话创建和空闲时登记事件。压缩时提醒宿主调用 `skstate_context`，并只使用返回的 procedure、state、observation。

Codex 写入 `.codex/hooks.json`（SessionStart、Stop）。钩子命令是 `skstate hook session-start` 与 `skstate hook session-end`；PATH 上有与当前安装一致的 `skstate` 时写这条命令，否则写带引号的 `python -m skstate hook session-start`。`python -m skstate.hooks.session_start` 保留为兼容入口。SessionStart 的 stdout 就是那份接管文书。`.codex/config.toml` 里会加上 `codex_hooks = true  # skstate`。卸载只删这一行，以及命令里含 `skstate.hooks` 或 `skstate hook session-` 的钩子。

用户没有在当前消息里同意时，不要调用 `skstate_hooks` 的 `install`。

## 一轮执行

1. `skstate_boot`。它自己登记会话，返回的 `boot_once` 是空数组，不需要再调开机工具。
2. 用户任务对得上某个技能时，`skstate_skills_list`，然后 `skstate_skill_view`，再 `skstate_run_start`。对不上任何技能时 `skstate_run_start`，`skill` 为 `scratch`（内置规程，不占技能列表）。
3. `skstate_context` 读取 P、Σ、O 和 task。
4. 宿主自行推理，调用 `skstate_step`，参数是 `state_patch` 和 `action`。
5. 宿主用自己的工具执行返回的 `action`。
6. `skstate_observe` 提交这一次的观察。
7. 回到第 3 步。结束或用户说「停」时调用 `skstate_finish`。

技能在 frontmatter 里声明状态形状：

```yaml
---
name: shelf-demo
metadata:
  skstate:
    state_schema:
      shelf: string
      qty: number
---
```

类型可以是 `string`、`number`、`boolean`、`array`、`object`、`any`。布尔值不会被当成数字。也可以把 `state_schema` 放在顶层。旧文件里的 `metadata.hermes.state_schema` 仍会读到。没有 schema 时，状态是开放对象，空值删除和嵌套合并照旧，`skstate_skill_view` 会用 `schema_open: true` 标出来。

写技能：`skstate skill new <name>` 生成模板，`skstate skill check [name]` 打印运行时读到的 name、description、schema；schema 为空时明确提示是开放对象。本进程装了 PyYAML 时按完整 YAML 读 frontmatter，否则用内置子集，遇到子集不认识的结构（`|`、`>`、锚点、流式集合）会报出具体行号。`skstate setup --example` 把示例技能 `shelf-demo` 复制到 `skills/`，其中 `pinned` 字段演示一条边界：以后还要用到的事实写进 state，不要指望它留在旧观察里。

## 工具

| 工具 | 作用 |
|---|---|
| `skstate_boot` | 返回接管文书和开机动作 |
| `skstate_skills_list` | 技能名和简介 |
| `skstate_skill_view` | 一份技能的规程和 schema |
| `skstate_run_start` | 把技能绑定为 P，并建立 Σ |
| `skstate_context` | 规程、当前状态、最新观察、task |
| `skstate_step` | 校验并合并状态补丁，返回要执行的动作 |
| `skstate_observe` | 替换最新观察 |
| `skstate_finish` | 结束 run |
| `skstate_hooks` | 查看、安装、卸载 OpenCode / Codex 钩子 |
| `skstate_hook_event` | 登记 session_start、session_end、signal |
| `skstate_status` | 数据目录、活动 run、`llm_api=false` |
| `skstate_audit` | 最多 30 条动作日志。用户要求审计时读取 |

## 数据放在哪里

`SKSTATE_HOME` 有值时，run、活动指针和钩子日志写在那里。否则写在 `<project>/.skstate`。`SKSTATE_PROJECT` 决定项目根，未设置时用当前工作目录。

技能从这三处读取：`SKSTATE_SKILLS`（操作系统路径分隔符分隔的多个目录）、`<project>/skills`、`<data_dir>/skills`。

## 分支与远端

- `origin` 是这个 fork：`git@github.com:linkerlin/hermes-skstate.git`。
- `upstream` 是 Nous Research 的 hermes-agent：`https://github.com/NousResearch/hermes-agent.git`。
- skstate 不随 upstream 的对话循环一起演进。要跑 `hermes` 对话的人按 upstream 的节奏升级；要跑 skstate 的人停在本 fork。

`skstate` 分支（尚未发布）将只包含演进方案阶段 1–4 里已经合并的命令。在发布之前，本文档只写下面这些，不再多写：

| 命令 | 作用 | 合并阶段 |
|---|---|---|
| `skstate` / `skstate serve` | stdio MCP 服务 | 阶段 0 |
| `skstate setup --platform opencode\|codex [--project-dir .] [--force] [--uninstall] [--example]` | 接入或卸载一个项目 | 阶段 1（`--example` 为阶段 3） |
| `skstate status` | 中文状态摘要 | 阶段 1 |
| `skstate hook session-start\|session-end` | IDE 调用的会话钩子 | 阶段 2 |
| `skstate skill new <name> [--project-dir .] [--force]` | 写技能模板 | 阶段 3 |
| `skstate skill check [name]` | 打印运行时读到的 schema | 阶段 3 |
| `skstate doctor` | 安装体检 | 阶段 4 |
| `skstate hooks --platform ... [--uninstall]` | 只装钩子的旧入口 | 阶段 0 |

尚未合并的（不要按不存在的命令操作）：`skstate setup` 的第三种 IDE 支持、独立安装包。真实 OpenCode / Codex 会话的检查单见 演进方案.md 阶段 6。

## 开发

```bash
python -m pytest tests/skstate -q -o addopts=
```

测试把 `SKSTATE_HOME` 和 `SKSTATE_PROJECT` 指到临时目录。
