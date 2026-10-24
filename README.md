# Cloudflare 入口优选与 EdgeTunnel 链式出口架构

本项目提供 Cloudflare 边缘优选入口与 EdgeTunnel 服务端分流方案。架构将网络入口握手与服务出站出口解耦，兼顾通用大流量访问的速度与 Gemini 等严风控服务的可用性。

```mermaid
flowchart LR
    client["客户端 (Shadowrocket)"]
    subgraph cf["Cloudflare 边缘网络"]
        entry["Anycast 优选入口 (CF-01 ~ CF-09)"]
        worker["EdgeTunnel Worker 运行时"]
        router{"命中 GO2SOCKS5 名单 ?"}
        entry --> worker --> router
    end
    socks["后置 SOCKS5 代理 (干净出口 VPS)"]
    dest_gen["通用网站 (YouTube / GitHub)"]
    dest_ai["AI 服务 (Gemini / Google)"]

    client -->|高可用 fallback 策略| entry
    router -->|否: 直连出站 (无限流量)| dest_gen
    router -->|是: 链式转发 (纯净 IP)| socks --> dest_ai
```

## 架构核心原则

- **入口与出口分离**。入口 Anycast IP 仅负责保障客户端到 Cloudflare 边缘的低延迟与抗丢包；外部目标网站（如 Gemini）识别的是 Worker 发起出站请求的出口 IP。
- **双轨分流**。海量多媒体与下载流量由 Cloudflare 边缘免费直连；Gemini 等对 IP 纯净度和地区有严格要求的请求，由 Worker 链式跳转至后置 SOCKS5 代理。
- **入口静态持久化**。取消 GitHub Actions 每日定时强制覆写，避免槽位底层 IP 频繁漂移导致本地断连。客户端配置采用 `fallback` 自动故障切换，提升网络容灾能力。

## EdgeTunnel 服务端配置

在 Cloudflare Pages 或 Workers 控制台设置以下环境变量，或在 `/admin` 后台保存：

| 变量名 | 必填 | 示例 | 说明 |
| :--- | :---: | :--- | :--- |
| **SOCKS5** | ✅ | `user:password@198.51.100.1:1080` | 后置干净出口 SOCKS5 代理服务器地址与认证凭据 |
| **GO2SOCKS5** | ✅ | `*google.com,*gemini.google.com` | 强制走 SOCKS5 代理的域名名单，多个域名用逗号分隔 |

配置生效后，访问通用网站依然享受 Cloudflare 节点直出；访问 Gemini 时，Worker 自动将流量转发至 SOCKS5 节点出站，避开 Google 对 Cloudflare ASN 13335 机房网段的封锁。

## 客户端配置 (Shadowrocket)

客户端配置文件位于 `clients/shadowrocket.conf`，说明文档见 `clients/README.md`。

配置已将 `CF-手动选择` 切换回 `CF-故障切换` (`fallback`)：

```ini
[Proxy Group]
CF-故障切换 = fallback,policy-regex-filter=^CF-0[1-9]$,interval=180,timeout=5,url=https://www.gstatic.com/generate_204

[Rule]
RULE-SET,https://raw.githubusercontent.com/iab0x00/ProxyRules/main/Rule/AI.txt,CF-故障切换
FINAL,CF-故障切换
```

当首选入口发生波动或超时时，小火箭在 5 秒内自动切换到下一个可用入口，无需人工干预。

## 链式路由验证

仓库提供本地端到端验证脚本 `scripts/verify_chain.py`，用于断言链式代理与分流状态：

```bash
# 执行本地链式路由与 Gemini 可达性检查
python3 scripts/verify_chain.py --ip 188.114.98.219
```

测试覆盖两项核心指标：
1. **通用出站验证**：测试经过节点后访问 Cloudflare trace 端点，获取直连出站 IP 与接入机房。
2. **Gemini 出站验证**：测试通过节点访问 `https://gemini.google.com/`，验证是否返回 200/302，并确认未出现人机验证或国家地区限制警告。

## 定时任务与离线检测说明

自动化 GitHub Actions 定时任务已禁用。避免云端美区测试机与国内本地运营商线路存在路由偏差，进而造成客户端订阅频繁被改写。用户可随时在 GitHub Actions 页面通过 `workflow_dispatch` 手动触发离线基准测试。
