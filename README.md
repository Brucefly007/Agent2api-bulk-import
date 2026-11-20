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

需要本机有 `docker` 命令，并且面板跑在 Docker 里。

```bash
python install.py                  # 默认容器名 agent2api
python install.py --container my-agent2api
python install.py --status
python install.py --uninstall      # 还原 index.html 并删除插件
```

装完刷新面板页面即可看到按钮（浏览器强刷一次）。

> 插件写在容器的可写层，**重建容器或升级镜像后会丢**，重跑一次 `install.py` 即可。

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

鉴权走面板同源 cookie（插件运行在已登录的面板页面里，不需要额外 token）。

## 文件说明

```
bulk-import.js                 插件本体（注入到面板 /app/ui/ 下）
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

只依赖标准库，覆盖 `install.py` 里对 `index.html` 的标签注入逻辑（插入位置、幂等、无 `</body>` 等边界）。

## License

MIT