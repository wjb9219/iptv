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
            ("pools.json", "pools.json"),
            ("retry_dead.json", "retry_dead.json")]
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


def fetch_seed():
    """从仓库 tools/ 取一份源池种子（本地同步过来的），比 /work 里的大就用它"""
    try:
        import base64
        api = "https://api.github.com/repos/wjb9219/iptv/contents/tools/pools.json"
        req = urllib.request.Request(api, headers={"User-Agent": "rebuild",
                                                   "Accept": "application/vnd.github+json"})
        d = json.loads(urllib.request.urlopen(req, timeout=40).read())
        data = base64.b64decode(d["content"])
        tmp = os.path.join(WORK, "pools_seed.json")
        open(tmp, "wb").write(data)
        cur = os.path.join(WORK, "pools.json")
        if count_pools(tmp) > count_pools(cur):
            shutil.copyfile(tmp, cur)
            log("源池种子：用仓库版 %d 台覆盖本地 %d 台" % (count_pools(tmp), count_pools(cur)))
    except Exception as e:
        log("源池种子未能获取（%r），沿用本地" % e)


def count_pools(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
        return len(d.get("order", []))
    except Exception:
        return 0


def round_once():
    # 状态同步：/p 上的池子比 /work 大就以 /p 为准，避免上轮误杀被固化
    for st in ("pools.json", "retry_dead.json"):
        w, o = os.path.join(WORK, st), os.path.join(OUT, st)
        if not os.path.exists(w):
            if os.path.exists(o):
                shutil.copyfile(o, w)
                log("初始状态：%s 从 %s 复制" % (st, o))
        elif st == "pools.json" and os.path.exists(o) and count_pools(o) > count_pools(w):
            shutil.copyfile(o, w)
            log("状态对齐：/p 的源池更大（%d > %d），以 /p 为准" % (count_pools(o), count_pools(w)))
    fetch_seed()
    prev = count_pools(os.path.join(WORK, "pools.json"))
    if not run("fetch_all.py"):
        log("抓源失败，本轮保留旧列表")
        return False
    run("pool_all.py")
    run("probe_all.py", timeout=2400)
    run("assemble.py")
    run("clean_pools.py")
    run("build_direct.py")
    run("build_m3u.py")
    run("build_pub.py")
    cur = count_pools(os.path.join(WORK, "pools.json"))
    if prev >= 300 and cur < prev * 0.9:
        log("! 本轮只测出 %d 台，比上轮 %d 少 %.0f%%，判定为探测异常，保留旧列表"
            % (cur, prev, 100.0 * (prev - cur) / prev))
        return False
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
