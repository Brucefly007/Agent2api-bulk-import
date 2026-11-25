# 常见问题

## 装完没看到按钮？

浏览器强刷一次（`Ctrl+F5` / `Ctrl+Shift+R`）。面板是单页应用，脚本注入到 HTML 了但页面没重载时看不到。

先确认装好了：

```bash
python install.py --status
```

正常应看到类似输出：

```
插件状态：
  [proxy] /bulk-import.js -> 200 application/javascript OK
  [proxy] 配置标记块：已存在
```

`container` 模式则是 `插件文件：… 字节` 与 `index.html 注入：已注入`。

如果 `--status` 显示 `未注入` / 文件缺失，重跑一次 `python install.py`。

## 装完按钮还是不出现，但接口是好的？

打开浏览器控制台，看 `bulk-import.js` 是否有加载错误（404 / 被 CSP 拦）。

- 404：`proxy` 模式的 `alias` 路径不对，检查 `--status` 里 `/bulk-import.js` 的状态码。
- 页面能加载但没按钮：说明面板改版后按钮锚点变了。插件会先用 `btn-add-account-2`、`btn-add-account`
  两个 id 匹配，再按「添加账号 / Add account」文本兜底；都匹配不上时把控制台里的按钮 DOM 片段发出来即可适配。

## 升级面板 / 重建容器后按钮消失了？

看用的是哪种模式：

- `proxy` 模式：插件文件与 nginx 配置都在宿主机，**重建容器不受影响**，一般不需要重装。
  若站点配置被面板工具重写，重跑 `python install.py --conf /path/to/site.conf` 即可。
- `container` 模式：插件写在容器可写层，镜像更新或容器重建会覆盖静态目录，重跑
  `python install.py` 就行（幂等，备份只在第一次生成）。

## `nginx -t` 失败怎么回滚？

`install.py` 在写配置前会自动备份成 `<site.conf>.bak-bulk-import-<时间戳>`，
并且**校验不通过就不会 reload**。回滚：

```bash
cp /path/to/site.conf.bak-bulk-import-<时间戳> /path/to/site.conf
nginx -t && nginx -s reload
```

或者直接 `python install.py --uninstall`（按标记块删除，不依赖备份）。

## 不知道该给 `--conf` 传什么？

先让脚本自己探测（多数环境能直接找到）；探测不到时：

```bash
nginx -T | grep -n "proxy_pass.*127.0.0.1"
```

找到指向面板容器端口的那一行，往上翻到最近的 `server {`，再往上找 `# configuration file <路径>:`，
那个路径就是 `--conf`。

## 能不能只装到某个路径 / 某个容器？

```bash
python install.py --container <容器名>
python install.py --ui /app/ui            # container 模式的静态目录
python install.py --mode proxy --conf /path/to/site.conf --port <对外端口>
```

## 导入报「导入内容必须是 JSON 对象」

说明 body 被发成了裸数组。本插件已经按 `{"accounts": [...]}` 发送；如果你是自己调接口，注意要包一层对象。

## 导入报「缺少 accounts 数组」

说明包了对象但键名不对（例如用了 `items`、`data`、`list`）。只认 `accounts`。

## 导入成功但账号查不了余额？

这是凭证本身不完整，不是导入的问题。比如某些提供商的 `accessToken` 必须由官方客户端换取，
手工抓到的只是授权码。导入时预览区会显示识别结果，但币值类字段是否可用取决于凭证质量。

## 会不会覆盖我已有的账号？

同 `provider` + 同身份（通常是 `uid`）会**更新**已有记录，不会产生重复；不同身份则新增。
建议先手工备份面板数据再批量导入。

## 有没有不写容器、也不动 nginx 的办法？

没有。面板 HTML 由服务端生成，插件必须在页面里加载一份脚本，能落地的位置只有两个：
容器静态目录（`container` 模式）或反代层注入（`proxy` 模式）。后者更稳，因为它不碰容器文件系统。