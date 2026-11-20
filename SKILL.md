---
name: model-availability-prober
description: 探测任意 OpenAI 兼容端点上哪些模型真的能调用。当用户遇到 400/404 "has no provider supported"、想知道某个 model id 是否可用、或需要在接入网关前筛出可用模型白名单时使用。每个模型只消耗 1 个 token。
---

# 模型可用性探测

## 功能

模型出现在平台目录里，不等于能真正调用。本 Skill 用 `max_tokens=1` 的最小请求，
逐个验证模型 ID 是否被端点接受，把「列得出但调不通」的模型一次性筛出来。

能区分这些情形：

| 情形 | 上游表现 | 本工具判定 |
|---|---|---|
| 目录挂名，无 provider 承接 | `has no provider supported` | 目录挂名，无 provider 承接 |
| 需要申请权限未开通 | 403 | 未开通权限 |
| 已下线但文档还在 | 404 | 模型不存在或已下线 |
| Key 无效 | 401 | API Key 无效 |
| 触发限流 | 429 | 限流（稍后重试） |
| 排队 / 维护中 | 503 / 超时 | 上游错误 / 超时 |

## 输入

| 参数 | 必填 | 说明 |
|---|---|---|
| `base_url` | 是 | OpenAI 兼容端点，如 `https://api-inference.modelscope.cn/v1` |
| `api_key` | 是 | 该端点的 Key |
| `models` | 是 | 模型 ID 列表 |
| `concurrency` | 否 | 并发数，默认 3；被 429 就降到 1 |
| `timeout` | 否 | 单模型超时秒数，默认 45 |

## 输出

每个模型一行：模型 ID、结论、HTTP 状态、耗时、上游原始报错。

## 使用

```bash
python scripts/probe.py \
  --base-url https://api-inference.modelscope.cn/v1 \
  --api-key "$KEY" \
  --models deepseek-ai/DeepSeek-V4-Pro-0813,Qwen/Qwen3.8-Flash-Next,ZhipuAI/GLM-5.2
```

作为库调用：

```python
from probe import probe_many

results = probe_many(
    base_url="https://api-inference.modelscope.cn/v1",
    api_key="...",
    models=["deepseek-ai/DeepSeek-V4-Pro-0813", "deepseek-ai/DeepSeek-V4-Or-Does-Not-Exist"],
    concurrency=3,
)
for r in results:
    print(r["model"], "可用" if r["ok"] else r["verdict"])
```

## 关键注意事项

1. **超时别设太短**。397B 这类大模型冷启动常超过 60 秒，超时设 45 秒会把
   「慢但正常」误判成不可用。大模型建议 180–300 秒。
2. **并发别开太大**。免费渠道并发上限通常很低，开太大会把 429 误判成模型不可用，
   正常模型也会被标成失败。
3. **只发 1 个 token 就够**。探测目的是验证端点是否接受这个 model id，
   不需要真实生成内容。
4. **扫描结果要落盘**。把可用清单存成白名单，定期重扫，模型下线时能第一时间发现。

## 适用场景

- 接入新渠道前先扫一遍，只把能调的放进网关配置
- 定期巡检已配置模型是否失效
- 排查网关 400/404 报错到底是模型问题还是鉴权问题
- 对比同一模型在不同端点的可用性