# Cloudflare 入口 IP 定时筛选

GitHub Actions 每天北京时间 09:15、21:15 运行，可在 Actions 手动执行。Mac 无需开机。GitHub 定时任务可能排队，不能保证准点。

使用 [CFData-WEB v1.8.3](https://github.com/PoemMisty/CFData-WEB) 的 HTTPing 初筛；从 Cloudflare 官方 IPv4 网段抽样约 480 个地址，并复测上次有效结果。每次抽样不同，不是扫描整个地址空间。

初筛后从新加坡、日本各取最多 20 个候选，美国取最多 60 个候选为补位留出余量；每个候选检查三次 HTTPS。请求必须全部成功、数据中心保持一致、单次耗时不超过 1500ms。每个国家按最大耗时、再按中位数排序。这是入口连通性检查，没有测试完整 EdgeTunnel 节点或下载速度。

订阅列表最多 9 个：新加坡、日本、美国各 3 个；新加坡或日本不足时由美国候选补齐。没有亚洲候选时使用 9 个美国候选。合格美国候选仍不足时只输出实际数量，不重复凑数；没有合格候选时保留上次列表并记录失败。

## 列表

- `global.txt`：上述 SG/JP/US 分配后的订阅列表，继续沿用原地址。
- `ip.txt`：仅供查看亚洲候选的辅助列表，限 JP/SG。按 trace 的 colo 和 Cloudflare 官方状态页的城市、国家对应表判断；没有亚洲合格结果时保留旧文件。首次未筛出结果时不会创建此文件。
- `status.json`：本次扫描时间、地区分布、实际发布数量、分配情况和列表更新时间。

云端结果反映 GitHub 服务器线路。Cloudflare Anycast 的路由随访问地点变化，同一个 IP 在家里可能连接到不同数据中心。入口地区不代表 EdgeTunnel 出口地区，也不能保证 Gemini 等服务可用。

## 接入 EdgeTunnel

将以下链接填入 EdgeTunnel「自定义优选」的「追加 API」，保存后刷新小火箭原有订阅。已使用此地址的客户端无需更换：

`https://raw.githubusercontent.com/RealRayTan/cf-preferred-ips/main/global.txt`

小火箭继续订阅 EdgeTunnel 原地址，GitHub 文本不是 VLESS 订阅。节点编号只是当次排序，更新后同名节点可能换成另一个 IP。

仓库公开，仅包含入口 IP 和测速结果；不存储 EdgeTunnel 管理密码、UUID、订阅密钥或 SOCKS5 凭据。无需手动配置 GitHub Secrets。

## 排查

在 Actions → Update preferred IPs → Run workflow 手动更新；扫描原始结果保留在运行附件里 7 天。`updated` 表示已发布 9 个入口，`partial` 表示数量不足；查看 `selected_countries` 确认实际地区分配。GitHub 公共仓库长时间没有活动可能停用定时运行；必要时在 Actions 重新启用。

参考：[EdgeTunnel 优选 API](https://blog.cmliussss.com/p/edt2/)；[GitHub 定时任务](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。
