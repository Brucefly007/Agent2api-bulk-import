#!/usr/bin/env python3
"""给 Agent2API 面板安装「批量导入凭证」插件。

两种部署模式，脚本会优先选更稳的那个：

  proxy      面板前面有 nginx（宝塔 / 1Panel / 手写 conf 都算）。
             插件文件放宿主机，nginx 直接对外提供，并在 </body> 前注入 script。
             优点：不写容器可写层，**容器重建 / 换镜像都不会丢**。

  container  容器直接对外，或本机没有可识别的 nginx 配置。
             把文件 docker cp 进面板静态目录并改 index.html。
             缺点：落在容器可写层，重建容器或升级镜像后会丢，需要重跑。

用法：
    python install.py                      # 自动选模式并安装
    python install.py --mode proxy         # 强制反代模式
    python install.py --mode container     # 强制容器模式
    python install.py --status             # 查看当前状态
    python install.py --uninstall          # 卸载并清理标记块
    python install.py --dry-run            # 只打印将要做的事

    python install.py --container agent2api        # 容器名（默认 agent2api）
    python install.py --conf /path/to/site.conf    # 指定 nginx 站点配置
    python install.py --port 8080                  # 指定面板对外端口
    python install.py --ui /app/ui                 # 容器内静态目录

只依赖本机 docker / nginx CLI 与 Python 标准库，不联网。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PLUGIN = "bulk-import.js"
TAG = '<script src="bulk-import.js"></script>'
URL_PATH = "/bulk-import.js"
HERE = os.path.dirname(os.path.abspath(__file__))

BEGIN = "# >>> agent2api-bulk-import (managed, do not edit) >>>"
END = "# <<< agent2api-bulk-import (managed, do not edit) <<<"


# --------------------------------------------------------------------------- #
# index.html 注入（container 模式；纯函数，便于单测）
# --------------------------------------------------------------------------- #
def inject_tag(html):
    """把 <script src="bulk-import.js"> 插到 </body> 前；已存在则原样返回。"""
    if TAG in html:
        return html, False
    if "</body>" in html:
        return html.replace("</body>", TAG + "</body>", 1), True
    return html + "\n" + TAG + "\n", True


def remove_tag(html):
    """卸载用：移除注入的标签。"""
    if TAG not in html:
        return html, False
    return html.replace(TAG, "", 1), True


# --------------------------------------------------------------------------- #
# nginx 配置处理（proxy 模式；纯函数，便于单测）
# --------------------------------------------------------------------------- #
def _block_end(text, open_idx):
    """从 `{` 的下标开始，返回与之配对的 `}` 下标。"""
    depth = 0
    for i in range(open_idx, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("配置文件花括号不配对")


def server_blocks(text):
    """返回所有 server 块的 (body_start, body_end)。"""
    out = []
    for m in re.finditer(r"(?m)^[ \t]*server[ \t]*\{", text):
        open_idx = text.index("{", m.start())
        close_idx = _block_end(text, open_idx)
        out.append((open_idx + 1, close_idx))
    return out


def find_server(text, port):
    """找到 proxy_pass 指向 127.0.0.1:<port> 的 server 块。"""
    needles = ("127.0.0.1:%d" % port, "localhost:%d" % port)
    for start, end in server_blocks(text):
        body = text[start:end]
        if any(n in body for n in needles):
            return start, end
    return None


def _location_block(text, start, end, matcher):
    """在 server 块里找形如 `location / {` 的位置块，返回 (body_start, body_end)。"""
    pat = r"(?m)^[ \t]*location[ \t]+%s[ \t]*\{" % matcher
    for m in re.finditer(pat, text[start:end]):
        open_idx = text.index("{", start + m.start())
        close_idx = _block_end(text, open_idx)
        return open_idx + 1, close_idx
    return None


def strip_managed(text):
    """移除所有 managed 标记块，返回 (新文本, 移除段数)。

    块以 `\\n` 开头（插入点紧跟在 `{` 之后）、以 END 行收尾；
    因此这里连同块尾那一行换行一起删除，能精确还原成安装前的文本。
    """
    removed = 0
    pat = (
        r"(?m)^[ \t]*" + re.escape(BEGIN) + r"[^\n]*\n"
        r".*?\n[ \t]*" + re.escape(END) + r"[ \t]*\n"
    )
    while True:
        m = re.search(pat, text, re.S)
        if not m:
            break
        text = text[: m.start()] + text[m.end():]
        removed += 1
    return text, removed


def patch_conf(text, port, asset_path, indent="    "):
    """在目标 server 块里加「静态直出 + </body> 注入」。幂等。

    返回 (新文本, 说明列表)。
    """
    text, removed = strip_managed(text)
    notes = []
    if removed:
        notes.append("已清理旧标记块 %d 处" % removed)

    found = find_server(text, port)
    if not found:
        raise ValueError("没有找到 proxy_pass 指向 127.0.0.1:%d 的 server 块" % port)

    start, _ = found
    static_block = (
        "\n" + indent + BEGIN + "\n"
        + indent + "location = %s {\n" % URL_PATH
        + indent + "    alias %s;\n" % asset_path
        + indent + "    types { }\n"
        + indent + "    default_type application/javascript;\n"
        + indent + '    add_header Cache-Control "no-cache, must-revalidate" always;\n'
        + indent + "}\n"
        + indent + END
    )
    text = text[:start] + static_block + text[start:]

    found = find_server(text, port)
    start, end = found
    loc = _location_block(text, start, end, r"/")
    if not loc:
        raise ValueError("server 块里没有 `location / {`，无法注入前端脚本")
    lstart, lend = loc
    inner = text[lstart:lend]

    inject = ""
    if 'proxy_set_header Accept-Encoding "";' not in inner:
        # sub_filter 只能处理未压缩响应，缺这行时补上
        inject += indent + "    proxy_set_header Accept-Encoding \"\";\n"
    inject += (
        indent + "    sub_filter '</body>' '<script src=\"%s\"></script></body>';\n" % PLUGIN
        + indent + "    sub_filter_once on;\n"
    )
    block = "\n" + indent + BEGIN + "\n" + inject + indent + END
    text = text[:lstart] + block + text[lstart:]
    notes.append("已在 server 块注入静态位置与 script 标签")
    return text, notes


def conf_has_managed(text):
    return BEGIN in text


# --------------------------------------------------------------------------- #
# 外部命令
# --------------------------------------------------------------------------- #
def run(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[:400])
    return r


def docker(*args, check=True):
    return run(["docker", *args], check=check)


def exec_sh(container, cmd):
    return (docker("exec", container, "sh", "-c", cmd).stdout or "").strip()


def nginx_bin():
    for cand in ("nginx", "/usr/sbin/nginx", "/usr/local/nginx/sbin/nginx"):
        if shutil.which(cand):
            return cand
        if cand.startswith("/") and os.path.exists(cand):
            return cand
    return None


def nginx_test_reload(dry=False):
    b = nginx_bin()
    if not b:
        raise RuntimeError("找不到 nginx 命令")
    t = run([b, "-t"], check=False)
    if t.returncode != 0:
        raise RuntimeError("nginx -t 失败：%s" % (t.stderr or t.stdout).strip()[:400])
    if dry:
        return "nginx -t 通过（dry-run，未 reload）"
    run([b, "-s", "reload"])
    return "nginx 已 reload"


def container_port(container):
    """从 docker inspect 取宿主机端口映射（优先 127.0.0.1 绑定）。"""
    out = docker("inspect", container, "--format", "{{json .NetworkSettings.Ports}}").stdout
    ports = json.loads(out or "{}")
    for _, bindings in ports.items():
        for b in bindings or []:
            hp = b.get("HostPort")
            if hp:
                return int(hp)
    raise RuntimeError("容器 %s 没有发布任何端口" % container)


def locate_conf(port):
    """用 `nginx -T` 找到含该端口反代的配置文件路径。"""
    b = nginx_bin()
    if not b or not port:
        return None
    dump = run([b, "-T"], check=False).stdout or ""
    marker = re.compile(r"(?m)^# configuration file (.+?):\s*$")
    hits = list(marker.finditer(dump))
    needles = ("127.0.0.1:%d" % port, "localhost:%d" % port)
    for i, m in enumerate(hits):
        start = m.end()
        end = hits[i + 1].start() if i + 1 < len(hits) else len(dump)
        chunk = dump[start:end]
        if any(n in chunk for n in needles):
            return m.group(1).strip()
    return None


def http_probe(port, path, timeout=5):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read(2048)
    except urllib.error.HTTPError as exc:
        ctype = exc.headers.get("Content-Type", "") if exc.headers else ""
        return exc.code, ctype, exc.read(512)
    except Exception as exc:
        return 0, "", str(exc).encode()


# --------------------------------------------------------------------------- #
# 各模式实现
# --------------------------------------------------------------------------- #
def container_status(container, ui):
    try:
        size = exec_sh(container, "wc -c < %s/%s 2>/dev/null" % (ui, PLUGIN))
        injected = exec_sh(container, "grep -c '%s' %s/index.html 2>/dev/null" % (PLUGIN, ui))
        bak = exec_sh(container, "ls -l %s/index.html.bak-bulkimport 2>/dev/null" % ui)
    except RuntimeError as exc:
        print("  读取失败：%s" % exc)
        return 1
    print("  [container] 插件文件：%s 字节" % (size.strip() or "缺失"))
    print("  [container] index.html 注入：%s"
          % ("已注入" if (injected.strip() or "0") not in ("", "0") else "未注入"))
    print("  [container] 备份：%s" % (bak.strip() or "无"))
    return 0


def install_container(container, ui, dry):
    if dry:
        print("  [dry-run] docker cp %s %s:%s/" % (PLUGIN, container, ui))
        print("  [dry-run] 备份并在 %s/index.html 的 </body> 前注入标签" % ui)
        return 0
    docker("cp", os.path.join(HERE, PLUGIN), "%s:%s/%s" % (container, ui, PLUGIN))
    print("  [container] 已上传插件")
    exec_sh(container, "cp -n %s/index.html %s/index.html.bak-bulkimport" % (ui, ui))
    with tempfile.TemporaryDirectory() as td:
        local = os.path.join(td, "index.html")
        docker("cp", "%s:%s/index.html" % (container, ui), local)
        with open(local, encoding="utf-8") as f:
            html = f.read()
        new_html, changed = inject_tag(html)
        if changed:
            with open(local, "w", encoding="utf-8") as f:
                f.write(new_html)
            docker("cp", local, "%s:%s/index.html" % (container, ui))
            print("  [container] 已注入 script 标签")
        else:
            print("  [container] script 标签已存在，跳过注入")
    return container_status(container, ui)


def proxy_paths(conf):
    """静态文件放 conf 同目录下的 bulk-import/ 子目录，便于定位与清理。"""
    d = os.path.join(os.path.dirname(os.path.abspath(conf)), "bulk-import")
    return d, os.path.join(d, PLUGIN)


def install_proxy(conf, port, dry):
    if not os.path.isfile(conf):
        raise RuntimeError("配置文件不存在：%s" % conf)
    with open(conf, encoding="utf-8") as f:
        text = f.read()

    asset_dir, asset_path = proxy_paths(conf)
    print("  [proxy] 配置文件：%s" % conf)
    print("  [proxy] 静态目录：%s" % asset_dir)

    new_text, notes = patch_conf(text, port, asset_path)
    for n in notes:
        print("  [proxy] %s" % n)

    if dry:
        print("  [dry-run] 将写入上述配置并 reload（未改动任何文件）")
        return 0

    bak = "%s.bak-bulk-import-%s" % (conf, time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(conf, bak)
    print("  [proxy] 已备份：%s" % bak)

    os.makedirs(asset_dir, exist_ok=True)
    dst = os.path.join(asset_dir, PLUGIN)
    shutil.copy2(os.path.join(HERE, PLUGIN), dst)
    os.chmod(dst, 0o644)
    print("  [proxy] 已放置插件：%s" % dst)

    with open(conf, "w", encoding="utf-8") as f:
        f.write(new_text)
    print("  [proxy] %s" % nginx_test_reload())
    return status(port=port, conf=conf)


def uninstall_proxy(conf, port, dry):
    with open(conf, encoding="utf-8") as f:
        text = f.read()
    new_text, removed = strip_managed(text)
    print("  [proxy] 移除标记块：%d 处" % removed)
    if dry:
        print("  [dry-run] 未改动任何文件")
        return 0
    if removed:
        bak = "%s.bak-bulk-import-%s" % (conf, time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(conf, bak)
        with open(conf, "w", encoding="utf-8") as f:
            f.write(new_text)
        print("  [proxy] 已备份：%s" % bak)
        print("  [proxy] %s" % nginx_test_reload())

    asset_dir, asset_path = proxy_paths(conf)
    if os.path.exists(asset_path):
        os.remove(asset_path)
        print("  [proxy] 已删除插件文件")
    try:
        if os.path.isdir(asset_dir) and not os.listdir(asset_dir):
            os.rmdir(asset_dir)
    except OSError:
        pass
    return 0


def uninstall_container(container, ui, dry):
    if dry:
        print("  [dry-run] 还原 %s/index.html 并删除 %s" % (ui, PLUGIN))
        return 0
    restored = exec_sh(
        container,
        "if [ -f {ui}/index.html.bak-bulkimport ]; then cp {ui}/index.html.bak-bulkimport "
        "{ui}/index.html && echo RESTORED; fi".format(ui=ui),
    )
    print("  [container] 还原 index.html：%s"
          % ("已从备份还原" if "RESTORED" in restored else "无备份"))
    exec_sh(container, "rm -f %s/%s" % (ui, PLUGIN))
    print("  [container] 已删除插件文件")
    return container_status(container, ui)


# --------------------------------------------------------------------------- #
# 状态
# --------------------------------------------------------------------------- #
def status(port=None, conf=None, container="agent2api", ui="/app/ui"):
    print("插件状态：")
    if port:
        code, ctype, body = http_probe(port, URL_PATH)
        ok = code == 200 and b"bulk-import" in body
        print("  [proxy] %s -> %s %s %s" % (URL_PATH, code, ctype, "OK" if ok else "异常"))
        if conf:
            try:
                with open(conf, encoding="utf-8") as f:
                    has = conf_has_managed(f.read())
                print("  [proxy] 配置标记块：%s" % ("已存在" if has else "不存在"))
            except OSError as exc:
                print("  [proxy] 配置读取失败：%s" % exc)
        else:
            print("  [proxy] 未指定配置文件，跳过配置检查")
    try:
        docker("inspect", container, "--format", "{{.State.Status}}")
        container_status(container, ui)
    except Exception:
        print("  [container] 容器 %s 不存在或 docker 不可用，跳过" % container)
    return 0


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def detect_mode(container, conf, port):
    """有可用 nginx 配置就优先 proxy（不写容器可写层）。"""
    if conf:
        return "proxy", conf, port or None
    try:
        p = port or container_port(container)
    except Exception:
        p = port
    if p and nginx_bin():
        found = locate_conf(p)
        if found:
            return "proxy", found, p
    return "container", None, p


def main():
    ap = argparse.ArgumentParser(description="给 Agent2API 面板安装「批量导入凭证」插件")
    ap.add_argument("--mode", choices=["auto", "proxy", "container"], default="auto")
    ap.add_argument("--container", default="agent2api", help="容器名（默认 agent2api）")
    ap.add_argument("--ui", default="/app/ui", help="容器内面板静态目录（container 模式）")
    ap.add_argument("--conf", default=None, help="nginx 站点配置（proxy 模式，缺省自动探测）")
    ap.add_argument("--port", type=int, default=None, help="面板对外端口（缺省自动探测）")
    ap.add_argument("--status", action="store_true", help="查看状态")
    ap.add_argument("--uninstall", action="store_true", help="卸载")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要做的事")
    a = ap.parse_args()

    try:
        mode, conf, port = detect_mode(a.container, a.conf, a.port)
        if a.mode != "auto":
            mode = a.mode
            if mode == "proxy" and not conf:
                conf = locate_conf(port or container_port(a.container))
        if a.port:
            port = a.port

        print("模式：%s%s%s" % (
            mode,
            "（配置 %s）" % conf if conf else "",
            "（端口 %d）" % port if port else "",
        ))

        if a.status:
            return status(port=port, conf=conf, container=a.container, ui=a.ui)

        if a.uninstall:
            if mode == "proxy" and conf:
                return uninstall_proxy(conf, port, a.dry_run)
            return uninstall_container(a.container, a.ui, a.dry_run)

        if mode == "proxy":
            if not conf:
                print("没有找到可用的 nginx 配置，改用 container 模式（可用 --conf 指定）。")
                return install_container(a.container, a.ui, a.dry_run)
            return install_proxy(conf, port, a.dry_run)
        return install_container(a.container, a.ui, a.dry_run)

    except FileNotFoundError:
        print("找不到 docker 命令。请确认已安装 Docker，且它在 PATH 里。")
        return 2
    except Exception as exc:
        print("失败：%s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())