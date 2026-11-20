#!/usr/bin/env python3
"""探测 OpenAI 兼容端点上哪些模型真的能调用。

每个模型只发一个 max_tokens=1 的请求，成本可忽略。
"""

import argparse
import json
import sys
import time
import concurrent.futures

try:
    import requests
except ImportError:
    sys.stderr.write("需要 requests：pip install requests\n")
    raise

PROBE_PROMPT = "hi"
MAX_TOKENS = 1
DEFAULT_TIMEOUT = 45


def classify(status_code, text):
    """把上游返回归类成可读结论。"""
    low = (text or "").lower()
    if "has no provider supported" in low:
        return "目录挂名，无 provider 承接"
    if status_code == 401:
        return "API Key 无效"
    if status_code == 403:
        return "未开通权限"
    if status_code == 404:
        return "模型不存在或已下线"
    if status_code == 429:
        return "限流（稍后重试）"
    if status_code in (500, 502, 503, 504):
        return f"上游错误 {status_code}"
    return f"HTTP {status_code}"


def probe_one(base_url, api_key, model, timeout=DEFAULT_TIMEOUT):
    """探测单个模型。"""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROBE_PROMPT}],
        "max_tokens": MAX_TOKENS,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    started = time.time()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        elapsed = int((time.time() - started) * 1000)
        if resp.status_code == 200:
            return {
                "model": model,
                "ok": True,
                "status": "200",
                "ms": elapsed,
                "verdict": "可用",
                "detail": "",
            }
        return {
            "model": model,
            "ok": False,
            "status": str(resp.status_code),
            "ms": elapsed,
            "verdict": classify(resp.status_code, resp.text),
            "detail": (resp.text or "")[:200].replace("\n", " "),
        }
    except requests.exceptions.Timeout:
        elapsed = int((time.time() - started) * 1000)
        return {
            "model": model,
            "ok": False,
            "status": "timeout",
            "ms": elapsed,
            "verdict": "超时（大模型冷启动可能 >60s）",
            "detail": f"超过 {timeout}s 未返回",
        }
    except Exception as exc:  # noqa: BLE001
        elapsed = int((time.time() - started) * 1000)
        return {
            "model": model,
            "ok": False,
            "status": "error",
            "ms": elapsed,
            "verdict": "请求异常",
            "detail": str(exc)[:200],
        }


def probe_many(base_url, api_key, models, concurrency=3, timeout=DEFAULT_TIMEOUT):
    """批量探测，保持输入顺序返回。"""
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(probe_one, base_url, api_key, m, timeout) for m in models]
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
    order = {m: i for i, m in enumerate(models)}
    results.sort(key=lambda r: order.get(r["model"], 0))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="探测 OpenAI 兼容端点上可用的模型")
    ap.add_argument("--base-url", required=True, help="如 https://api-inference.modelscope.cn/v1")
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--models", required=True, help="逗号分隔或每行一个")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--json", action="store_true", help="输出 JSON 而不是表格")
    args = ap.parse_args(argv)

    models = [m.strip() for m in args.models.replace(",", "\n").splitlines() if m.strip()]
    if not models:
        ap.error("至少给一个模型 ID")

    results = probe_many(args.base_url, args.api_key, models, args.concurrency, args.timeout)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        width = max(len(r["model"]) for r in results) + 2
        for r in results:
            mark = "OK  " if r["ok"] else "FAIL"
            print(f'{mark}  {r["model"]:<{width}} {r["verdict"]:<24} {r["status"]:>7}  {r["ms"]:>6}ms')
            if not r["ok"] and r["detail"]:
                print(f'        {r["detail"]}')

    ok = sum(1 for r in results if r["ok"])
    total = len(results)
    print(f"\n{total} 个模型，{ok} 可用，{total - ok} 不可用。消耗约 {total} token。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())