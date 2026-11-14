# -*- coding: utf-8 -*-
"""一轮完整重建：抓源 -> 聚合 -> 测活 -> 合成 -> 生成四份列表 -> 通知网关热加载
跑在 NAS 容器里，默认每 6 小时一轮。"""
import os, sys, time, json, shutil, subprocess, urllib.request

WORK = os.environ.get("RB_WORK", "/work")          # 脚本与状态目录
OUT = os.environ.get("RB_OUT", "/p")               # 输出目录（docker/iptv）
GW = os.environ.get("RB_GW", "http://127.0.0.1:8101/api/reload")
SLEEP = int(os.environ.get("RB_SLEEP", "21600"))
ONCE = os.environ.get("RB_ONCE", "0") == "1"


def log(m):
    print("[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), m), flush=True)


def run(script, timeout=1800):
    log("== 运行 %s" % script)
    t0 = time.time()
    p = subprocess.run([sys.executable, "-u", script], cwd=WORK, timeout=timeout)
    log("== %s 结束 rc=%s %.0fs" % (script, p.returncode, time.time() - t0))
    return p.returncode == 0


def publish():
    """把生成的四份列表放到对外目录"""
    jobs = [("_live_direct.m3u", "live_full.m3u"),
            ("_live_pub.m3u", "live_public.m3u"),
            ("_live_gw.m3u", "live_gw.m3u"),
            ("live_gw_test.m3u", "live_gw_test.m3u"),
            ("pools.json", "pools.json")]
    for src, dst in jobs:
        s, d = os.path.join(WORK, src), os.path.join(OUT, dst)
        if not os.path.exists(s):
            log("  缺文件，跳过 %s" % src)
            continue
        shutil.copyfile(s, d)
        log("  %s -> %s (%dB)" % (src, dst, os.path.getsize(d)))


def reload_gw():
    try:
        r = urllib.request.urlopen(GW, timeout=8)
        log("  网关热加载：%s" % r.read().decode("utf-8", "ignore").strip())
    except Exception as e:
        log("  网关热加载失败（不影响文件）：%r" % e)


def round_once():
    if not run("fetch_all.py"):
        log("抓源失败，本轮保留旧列表")
        return False
    run("pool_all.py")
    run("probe_all.py", timeout=2400)
    run("assemble.py")
    run("build_direct.py")
    run("build_m3u.py")
    run("build_pub.py")
    publish()
    reload_gw()
    try:
        rep = json.load(open(os.path.join(WORK, "round_report.json"), encoding="utf-8"))
        log("本轮账本：总 %d 台，新增 %d，复活 %d，重试名单 %d"
            % (rep.get("total", 0), len(rep.get("added", [])),
               len(rep.get("revived", [])), len(rep.get("dead", []))))
    except Exception:
        pass
    return True


if __name__ == "__main__":
    while True:
        log("===== 新一轮开始 =====")
        try:
            round_once()
        except Exception as e:
            log("本轮异常：%r" % e)
        if ONCE:
            break
        log("休眠 %ds 等下一轮" % SLEEP)
        time.sleep(SLEEP)
