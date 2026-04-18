# remit-compare — Agent Guide

## 项目目的
命令行工具，实时对比主流跨境汇款渠道（如 Wise、Remitly、Western Union）的费率、手续费和到账时间，帮助用户选择最优方案。

## MVP 范围
- 支持 3–5 个主流汇款渠道
- 输入：发送金额、发送币种、收款币种
- 输出：表格展示各渠道报价（费率、手续费、到账金额、预计到账时间）
- 按总成本排序

## 技术栈
| 组件 | 选型 |
|------|------|
| 语言 | Python 3.11 |
| 依赖管理 | uv |
| CLI | Typer |
| HTTP | httpx（异步） |
| 测试 | pytest + pytest-httpx + pytest-asyncio |
| Lint/格式 | ruff |

## 目录约定
```
src/remit_compare/
  core/           # Quote dataclass、BaseProvider 抽象类、汇率工具
  providers/      # 每个渠道一个文件，实现 BaseProvider
  cli.py          # Typer 入口，组合各 provider
tests/
  core/           # 测试 core 模块
  providers/      # 每个 provider 配套测试，使用 pytest-httpx mock HTTP
```

## 数据模型
```python
@dataclass
class Quote:
    provider_name: str
    send_amount: float
    send_currency: str
    receive_amount: float
    receive_currency: str
    fee: float
    exchange_rate: float
    total_cost_in_send_currency: float
    estimated_arrival_hours: int
```

## 验收标准
- `uv run remit-compare compare 1000 --from USD --to CNY` 能输出对比表格
- 所有 provider 使用 httpx 异步请求，不阻塞
- `pytest -x` 全部通过，覆盖每个 provider 的正常路径和错误路径
- `ruff check src tests` 零警告

## 非目标（明确不做）
- 不做用户账号/登录系统
- 不对接真实银行 API（使用公开汇率接口或 mock 数据）
- 不做 Web 前端或 GUI
- 不做数据库持久化
- 不做 Docker 化

## Agent 工作规则
1. **最小改动原则**：每次只修改与任务直接相关的文件，不顺手重构其他模块。
2. **改完必须跑测试**：每次改动后执行 `uv run pytest -x`，有失败立即修复再提交。
3. **新增 provider 必须配套测试**：在 `tests/providers/test_<name>.py` 中覆盖正常返回和 HTTP 错误两种场景。
4. **不破坏 BaseProvider 接口**：`get_quote` 签名和 `Quote` 字段不得随意修改；如需扩展，先在此文件讨论。
5. **HTTP 请求全部用 httpx 异步**：禁止使用 `requests` 或同步 httpx。
6. **ruff 零警告**：提交前运行 `uv run ruff check src tests`。
