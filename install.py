#!/usr/bin/env python3
"""把「批量导入凭证」注入 Agent2API 面板（Docker 部署）。

做的事：
  1. 把 bulk-import.js 复制进容器的 /app/ui/
  2. 在容器的 index.html 末尾加一行 <script src="bulk-import.js"></script>
  3. 原 index.html 备份成 index.html.bak-bulkimport（只在第一次备份）

用法：
    python install.py                 # 安装（幂等）
    python install.py --status        # 查看状态
    python install.py --uninstall     # 还原并删除插件
    python install.py --container X   # 指定容器名（默认 agent2api）

只依赖本机 docker CLI，不需要 SSH。
"""
import argparse
import os
import subprocess
import sys
import tempfile

PLUGIN = "bulk-import.js"
TAG = '<script src="bulk-import.js"></script>'
HERE = os.path.dirname(os.path.abspath(__file__))


def docker(*args):
    r = subprocess.run(["docker", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[:300])
    return (r.stdout or "").strip()


def exec_sh(container, cmd):
    return docker("exec", container, "sh", "-c", cmd)


def status(container, ui):
    try:
        size = exec_sh(container, f"wc -c < {ui}/{PLUGIN} 2>/dev/null")
        injected = exec_sh(container, f"grep -c '{PLUGIN}' {ui}/index.html 2>/dev/null")
        bak = exec_sh(container, f"ls -l {ui}/index.html.bak-bulkimport 2>/dev/null")
    except RuntimeError as e:
        print(f"读取失败：{e}")
        return 1
    print(f"插件文件：{size.strip() or '缺失'} 字节")
    print(f"index.html 注入：{'已注入' if (injected.strip() or '0') not in ('', '0') else '未注入'}")
    print(f"备份：{bak or '无'}")
    return 0


def inject_tag(html):
    """把 <script src="bulk-import.js"> 插到 </body> 前；已存在则原样返回。"""
    if TAG in html:
        return html, False
    if "</body>" in html:
        return html.replace("</body>", TAG + "</body>", 1), True
    return html + "\n" + TAG + "\n", True


def install(container, ui):
    src = os.path.join(HERE, PLUGIN)
    if not os.path.exists(src):
        print(f"缺少 {src}")
        return 1

    # 1) 上传插件（走 docker cp，跨平台不需要容器里有 python）
    docker("cp", src, f"{container}:{ui}/{PLUGIN}")
    print("已上传插件")

    # 2) 备份 index.html（幂等）
    exec_sh(container, f"cp -n {ui}/index.html {ui}/index.html.bak-bulkimport")

    # 3) 取回 index.html → 本地注入 → 拷回
    with tempfile.TemporaryDirectory() as td:
        local = os.path.join(td, "index.html")
        docker("cp", f"{container}:{ui}/index.html", local)
        with open(local, encoding="utf-8") as f:
            html = f.read()
        new_html, changed = inject_tag(html)
        if not changed:
            print("script 标签已存在，跳过注入")
        else:
            with open(local, "w", encoding="utf-8") as f:
                f.write(new_html)
            docker("cp", local, f"{container}:{ui}/index.html")
            print("已注入 script 标签")

    return status(container, ui)


def uninstall(container, ui):
    restored = exec_sh(
        container,
        f"if [ -f {ui}/index.html.bak-bulkimport ]; then "
        f"cp {ui}/index.html.bak-bulkimport {ui}/index.html && echo RESTORED; fi")
    print("还原 index.html：", "已从备份还原" if "RESTORED" in restored else "无备份")
    exec_sh(container, f"rm -f {ui}/{PLUGIN}")
    print("已删除插件文件")
    return status(container, ui)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", default="agent2api", help="Agent2API 容器名")
    ap.add_argument("--ui", default="/app/ui", help="容器内面板静态目录")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()
    try:
        if a.status:
            return status(a.container, a.ui)
        if a.uninstall:
            return uninstall(a.container, a.ui)
        return install(a.container, a.ui)
    except FileNotFoundError:
        print("找不到 docker 命令。请确认已安装 Docker，且它在 PATH 里。")
        return 2
    except RuntimeError as e:
        print(f"操作失败：{e}")
        print(f"提示：确认容器名正确（当前 {a.container}），可用 docker ps 查看。")
        return 2


if __name__ == "__main__":
    sys.exit(main())