<p align="center"><img src="assets/logo.svg" alt="run-capsule logo" width="640"></p>

# run-capsule

**给实验输入一个可核验、便于口头交流的名字。**

run-capsule 是一个 Python 标准库 CLI：仅对你明确选择的输入文件和目录计算 SHA256，将文件清单、JSON 配置和扫描策略组成确定性的实验清单，再生成一个可读的运行标签。它不复制数据、不执行实验，也不上传任何内容。

适合 EIT（电阻抗成像）实验中记录电压文件、激励协议和求解参数之间的对应关系，也适合一般科学计算。示例电压和参数完全为合成数据，不代表真实设备、患者或验证过的测量结果。

## 快速开始

要求 Python 3.10+。运行和测试不需要安装第三方依赖。在项目目录执行：

```sh
python -m run_capsule snapshot input --root examples \
  --config examples/config.json --output /tmp/eit-run.json
python -m run_capsule verify /tmp/eit-run.json --root examples
python -m unittest discover -v
```

Windows 请将 `/tmp/eit-run.json` 换成一个尚不存在的可写路径。代码使用 pathlib，不依赖 Unix 命令。

可选安装：`python -m pip install .`，然后使用 `run-capsule` 命令。构建工具为 setuptools；未预装时 pip 可能需要联网下载构建工具。直接使用 `python -m run_capsule` 不需要构建或联网。

成功创建会输出形如 `cedar-iris-...-0123abcd` 的标签，具体词语由摘要决定；核验成功返回：

```json
{
  "missing": [],
  "modified": [],
  "new": [],
  "ok": true,
  "skipped_symlinks": []
}
```

## 常用流程

### 固定实验范围

```sh
python -m run_capsule snapshot input/voltages.csv config.json \
  --root examples --config examples/config.json --output /tmp/eit-inputs.json
```

位置参数相对 `--root`，必须使用规范的相对 POSIX 路径，即使在 Windows 也使用 `/`。`--config`、`--output` 以及 verify 的清单路径则相对当前工作目录。`--root` 默认为当前目录。绝对输入路径、`..`、反斜杠、盘符、`./input` 均被拒绝。

- 选择文件：核验此文件；旁边新增的文件不在范围内。
- 选择目录：递归选择其中的普通文件，并在核验时报告目录内新增文件。
- 选择 `.`：明确选择根目录下所有符合策略的文件。请只对经过检查的实验目录这样做。
- 重复选择、父子范围重叠不会重复计算文件；不同的选择范围仍属于不同的清单身份。
- 输入不存在会报错；空目录合法，但不记录目录实体。

### 包含隐藏文件

```sh
python -m run_capsule snapshot input --root examples \
  --include-hidden --output /tmp/eit-with-hidden.json
```

默认跳过任何路径分量以 `.` 开头的文件和目录；显式选择隐藏路径也需要这个开关。它按名称判断，不检查 Windows 隐藏属性。**隐藏过滤不是秘密扫描器**：选择的普通文件可能含有秘密；元数据会以明文写入清单。不要在配置里写令牌、密码、患者信息或身份标识。

### 搬到另一台计算机

自行复制输入目录后，用新根目录核验原清单：

```sh
python -m run_capsule verify saved-run.json --root restored-experiment
```

清单不保存绝对路径、时间戳、用户名或机器信息。相对路径、文件原始字节、配置和策略相同，即可得到相同摘要。换行转换、改名、文件内容变化会改变身份。权限、mtime、目录布局中的空目录变化不计入身份。

### 观察差异

`modified` 是内容或大小变化；`missing` 是原记录文件消失；`new` 是原选择目录中出现的新文件。列表均按路径排序。核验不修改输入、不更新清单，也不自动认可变化。确认新的实验输入后，另选输出名再次 snapshot。

退出码：`0` 创建成功或文件核验通过；`1` 核验发现差异；`2` 输入、权限、文件系统、清单或参数错误。选中的目录被文件替换、或选中路径变成符号链接，也视为操作错误而非普通差异。

## 清单格式 v1

完整例子见 [examples/manifest.json](examples/manifest.json)。字段含义：

| 字段 | 含义 |
| --- | --- |
| `schema` | 固定为 `run-capsule/v1` |
| `inputs` | 按路径排序的选择范围，包含 `path` 和 `kind`（`file` / `directory`） |
| `policy.include_hidden` | 是否包含点号隐藏项 |
| `policy.exclude` | 输出文件在根目录内时的相对路径，核验也排除此路径 |
| `policy.symlinks` | 固定为 `skip`，不跟随递归发现的符号链接 |
| `config` | 显式读取的 JSON 对象，嵌套数组/对象合法；NaN/Infinity 不合法 |
| `files` | 按路径排序的 `path`、字节数 `size`、64 位十六进制 `sha256` |
| `digest` | 下述规范化载荷的完整 SHA256 |
| `label` | 便于交流的短标签 |
| `skipped_symlinks` | 扫描时跳过的链接路径，诊断信息，不参与摘要 |

摘要载荷严格由 `schema`、`inputs`、`policy`、`config`、`files` 组成。以 Python `json.dumps(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)` 编码为 UTF-8 后计算 SHA256。最终清单使用缩进排版，排版不影响摘要。修改配置对象会改变摘要；配置文件本身只有显式选择后才作为文件核验。verify 验证的是清单内保存的配置，不会重新打开当初的 `--config` 文件。

可读标签使用32 个自然/实验词语。取摘要第 9–16 个十六进制字符表示的整数，自低位起读取五个 5-bit 块选词，再附加摘要前八个十六进制字符。这给出 57 位短标识信息，而非完整 256 位身份。**标签可能碰撞，不可用于身份认证、签名、访问控制或大规模去重；正式记录应保留完整 digest。**

清单的自检可发现意外改动，但没有密钥或签名。攻击者能同时修改内容和摘要，因此清单不是来源可信的证明。

## 安全边界和限制

- 只读取指定范围和显式配置，不查询环境变量、Git 历史、主目录、设备、网络或凭据；不会自动寻找输入或秘密。
- 递归发现的符号链接被跳过并报告，链接目标不读取。选择的路径或其中的祖先是符号链接时拒绝。`--root` 自身会解析到真实目录，这等于由调用者选定实际根目录。
- 输出若在根目录内会排除；CLI 拒绝覆盖任何已有输出，不提供强制覆盖选项。输出父目录必须已存在。输出路径会影响 `policy.exclude`，因而根目录内的不同输出名会产生不同摘要；需要跨机器比较时统一输出相对路径，或将清单放在根目录外。
- 普通文件以 1 MiB 块读取，清单元数据保存在内存中。FIFO、socket、设备等不支持。符号链接与硬链接不同：硬链接当作普通文件，按各自相对路径记录。
- 单文件哈希前后检查大小、mtime 和 inode，尽量发现写入中的数据；不是原子文件系统快照。目录可能并发变化，恶意路径替换竞态也不能跨平台完全防护。**请停止采集、固定输入目录并在可信文件系统中运行。**
- 未记录的空目录和链接目标变化不属于文件差异。`skipped_symlinks` 单独列出；它非空不必然使 `ok` 为 false。
- 没有数据归档、环境锁文件生成、代码版本发现、仪器校准校验、科学正确性判断、签名、加密、远程同步或重建实验功能。要重现实验，还应显式选择代码/协议/依赖记录，或将版本号作为配置保存。
- 不同 JSON 数值写法经过 Python 解析后可能归一化；`1` 和 `1.0` 仍可产生不同摘要。字符串的 Unicode 规范化形式不会自动转换。跨语言重新实现需匹配上述编码约定。

## 项目结构与验证

```text
run_capsule/core.py       选择、流式哈希、规范化、标签、核验
run_capsule/__main__.py   argparse CLI、JSON 输入输出、退出码
examples/                合成 EIT 输入、参数、可核验清单
assets/logo.svg          矢量标识
tests/test_capsule.py    单元与 CLI 子进程测试
```

测试覆盖确定性、SHA256 已知值、元数据顺序、差异分类、显式范围、重叠去重、隐藏文件、输出排除、路径穿越、符号链接、篡改检测、跨根目录搬移、mtime、空目录、Unicode、非法数值以及 CLI 成功/差异/拒绝覆盖。Linux 已运行通过；未声称做过 Windows 或 macOS 实机验证。
