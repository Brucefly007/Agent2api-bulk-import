# Agent2API · 批量导入凭证

给 [Agent2API](https://github.com/) 面板加一个「批量导入」入口：把多个账号 JSON 一次性丢进去，
**自动识别每份凭证属于哪个提供商**，然后调面板自带接口写入。

- 账号页工具栏「添加账号」右边多一个 **批量导入** 按钮
- 弹窗支持拖入多个 `.json`，或直接粘贴数组 / 单个账号 / 整库导出内容
- 导入前先分组预览：`codearts × 67`、`trae × 5`，未识别会标红
- 同提供商 + 同身份会**更新**原凭证，不会重复添加

## 界面

```
账号页工具栏：  刷新 | 折叠 | 添加账号 | 批量导入 | 查询余额
导入弹窗：      拖拽区 + 粘贴框 + 识别预览 + 导入结果
```

## 安装

只需要本机有 `docker` 和 Python 3.8+，不需要 SSH、不需要联网。

```bash
python install.py                 # 自动选模式并安装
python install.py --status        # 查看状态
python install.py --uninstall     # 卸载
```

装完刷新面板页面（建议 `Ctrl+Shift+R` 强刷一次）即可看到按钮。

### 两种部署模式

`install.py` 会自动判断，也可以强制指定（`--mode`）。

| | `proxy` | `container` |
|---|---|---|
| 适用 | 面板前面有 nginx 反代（宝塔 / 1Panel / 手写 conf） | 容器端口直接对外，或探测不到 nginx 配置 |
| 做法 | 插件文件放宿主机，nginx 直接对外提供 + 在 `</body>` 前注入 `script` | `docker cp` 进面板静态目录 + 改 `index.html` |
| 容器重建后 | **不丢**，配置和文件都在宿主机 | **会丢**，需要重跑一次 |
| 推荐 | ✅ 默认优先 | 兜底 |

> **为什么要区分模式**：Agent2API 3.5 起面板 HTML 由二进制内嵌生成，
> 改容器里的 `index.html` 不会生效，而且容器重建 / 换镜像后写在可写层的文件会消失。
> `proxy` 模式把插件放在宿主机、由 nginx 注入，这两点都绕开了。

### 常用参数

```bash
python install.py --mode proxy                       # 强制反代模式
python install.py --conf /path/to/site.conf          # 指定站点配置（不给则用 nginx -T 自动探测）
python install.py --port 8080                        # 面板对外端口（不给则读 docker 端口映射）
python install.py --container agent2api              # 容器名（默认 agent2api）
python install.py --ui /app/ui                       # 容器内静态目录（container 模式）
python install.py --dry-run                          # 只打印将要做的事，不改任何文件
```

`proxy` 模式的落点：

```
<site.conf 所在目录>/bulk-import/bulk-import.js     插件文件
<site.conf>                                         追加一个 managed 标记块
```

写配置前会自动备份成 `<site.conf>.bak-bulk-import-<时间戳>`，并先跑 `nginx -t`，不通过就不 reload。

### 幂等与卸载

插入的内容用成对的标记注释包住：

```nginx
# >>> agent2api-bulk-import (managed, do not edit) >>>
...
# <<< agent2api-bulk-import (managed, do not edit) <<<
```

重复执行 `install.py` 会先清掉旧标记块再重建，不会叠加；
`--uninstall` 按标记块精确删除并 `nginx -s reload`，配置能还原到安装前的字节状态（有单测覆盖）。

## 支持的凭证格式

每个文件可以是：

- 一个账号对象（`{"provider": "...", ...}`）
- 一个数组（`[{...}, {...}]`）
- 带包装的结构（`{"accounts": [...]}`、`{"items": [...]}`）
- 面板「整库导出」的数组（同 provider + 同身份会更新）

账号字段示例见 [`examples/account.example.json`](examples/account.example.json)。

## 提供商识别规则

按顺序尝试，命中即止：

1. 对象里的 **`provider`** 字段
2. **`pluginIdentity`** 前缀：`codearts-…` → codearts，`trae-…` → trae
3. 特征字段：`security_token` + `domain_id` → codearts；`devicePrivateKey` + `enterpriseId` → trae
4. **`apiHost`** 域名：含 `trae` / `huaweicloud` / `codearts` / `loomy` / `workbuddy`

识别不出来的不会丢弃，会以「(未识别)」单独列出来，导入时原样提交，由面板自己判断。

## 面板接口

```
POST /api/accounts/import
Content-Type: application/json
Body: {"accounts": [ … ]}
```

响应：

```json
{"data": {"total": 3, "added": 2, "updated": 1, "skipped": 0,
          "failed": 0, "errors": [], "importedIds": ["…"]}}
```

注意 **body 必须是 `{"accounts": [...]}` 这种对象包裹的形式**：
直接提交数组会返回 `400 导入内容必须是 JSON 对象`；`items` / `data` / `list` / 单个对象
会返回 `400 缺少 accounts 数组`。

## 目录结构

```
bulk-import.js                 插件本体（前端，同源 fetch，走 cookie 鉴权）
install.py                     安装 / 卸载 / 状态
examples/account.example.json  账号 JSON 示例（已脱敏）
docs/FAQ.md                    常见问题
tests/                         install.py 的单元测试
.github/workflows/ci.yml       语法检查 + 单元测试
```

## 测试

```bash
python -m unittest discover -s tests -v
```

只依赖标准库，覆盖两类纯逻辑：

- `index.html` 标签注入：插入位置、幂等、无 `</body>` 等边界
- nginx 配置改写：server 块定位、标记块插入位置、`Accept-Encoding` 去重、
  幂等、缺 `location /` 或目标 server 时的报错、卸载后字节级还原

CI 还会跑 `python -m py_compile install.py`、`node --check bulk-import.js`
和示例 JSON 的合法性校验。

## 兼容性

- Agent2API 3.4 / 3.5 面板均可；按钮锚点按 id 多候选匹配，回落文本匹配，改动面板不会失联
- 插件只调面板已有的 `/api/accounts/import`，不改后端、不额外开端口、不需要 token
- 卸载后不留残留：标记块删除、静态文件删除、空目录清理

## License

MIT