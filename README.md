# Cloudflare 入口 IP 定时筛选

定期检查 Cloudflare 候选入口，为边缘转发服务提供可更新的连接地址。

```mermaid
flowchart TB
    client["客户端"]
    subgraph cf["Cloudflare 边缘网络"]
        entry["网络入口"]
        relay["边缘转发服务"]
        entry <--> relay
    end
    destination["目标服务"]
    client <-->|应用流量| entry
    relay <-->|出站连接| destination

    schedule["GitHub Actions 定时检查"] --> candidates["筛选后的候选入口"]
    candidates -.->|用于生成连接配置| relay
```

客户端连接 Cloudflare 入口后，由部署在边缘的转发服务建立到目标服务的出站连接，并将响应传回客户端。图中省略了具体协议、认证和可选的中间转发环节。

本仓库负责图中的定时检查与入口筛选。GitHub 不承载应用流量；筛选结果供转发服务生成连接配置时引用。

## 自动筛选

GitHub Actions 每天运行两次，无需本地设备持续开机。任务使用 [CFData-WEB](https://github.com/PoemMisty/CFData-WEB) 对 Cloudflare 官方 IPv4 网段进行抽样初筛，再通过重复 HTTPS 请求检查入口连通性。

通过初筛的候选还需使用 [sing-box](https://github.com/SagerNet/sing-box) 建立真实转发连接，完成多轮目标页面访问、定量下载和短时持续传输检查。失败或返回拦截页面的候选不会进入发布结果，排序以实际转发响应为依据。定时任务可能受 GitHub 排队影响。

目标是保留最多 9 个入口，新加坡、日本、美国各 3 个。新加坡或日本候选不足时，由美国候选补齐；没有亚洲候选时使用美国候选。合格数量仍不足时只保留实际数量，没有合格结果时保留上次有效内容。

## 结果的适用范围

地区标记来自检测时实际连接到的 Cloudflare 数据中心。由于 Anycast 路由随访问地点变化，同一个入口在不同网络下可能连接到不同机房，云端排序也不代表本地线路的表现。

检查覆盖入口、真实转发请求与有限时长的传输，页面检测不代表视频播放、登录、AI 地区资格或全天稳定性。入口地区与最终出口地区是两个独立概念，实际使用效果仍需在客户端验证。

仓库只保存候选入口和检测结果。测试所需认证配置保存在 GitHub Secrets，公开结果不包含认证信息。
