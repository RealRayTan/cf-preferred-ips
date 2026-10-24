# 客户端配置

## 小火箭

`shadowrocket.conf` 基于使用者提供的懒人配置合并而成，包含原有服务分流、广告过滤和 CF 故障切换，不含节点认证信息。节点仍由原来的 EdgeTunnel 订阅提供；不要把它当成节点订阅导入。

在小火箭「配置」页添加以下地址，下载后选择「使用配置」，首页「全局路由」选择「配置」：

```
https://raw.githubusercontent.com/RealRayTan/cf-preferred-ips/main/clients/shadowrocket.conf
```

配置保留原有 DNS、Host、Google 重写与服务分流设置，把原来使用 `PROXY` 的规则改为 `日常流媒体`，并增加 `AI-专线` 独立调度 Gemini/Google 流量。Steam 下载域名和 SteamCN 直连，Steam 其他服务仍按原规则代理。首次下载后选择「使用配置」，以后只使用这一份，不必来回切换配置。

原文本没有广告拦截规则，本版补充 AdvertisingLite 广告域名集与规则集；域名拦截不需要安装解密证书，但不能保证清除 YouTube 视频等与内容共用域名的广告。原文本只指定 Google 中国域名的解密范围，本版保留该范围，没有新增证书或开启 HTTPS 解密。

Apple、WeChat、Global、China 改为原生 Shadowrocket 格式；Apple、Global、China 按规则作者说明同时引用 `_Domain.list`，避免遗漏拆分的域名规则。其余服务规则保留，没有仅因名称相似就删除。

配置的 `update-url` 已指向本仓库合并版。远程规则集仍来自各原作者并随其更新。配置源码保持精简，去掉了教学示例注释和空配置项。

策略组包含两大专线：
- `日常流媒体`：默认直连 `CF-MEDIA`（由 EdgeTunnel 订阅提供），专职负责 YouTube 4K、Twitter/X、GitHub 及通用下载，享受极速千兆带宽。
- `AI-专线`：独立调度 Gemini 等 AI 业务。当前处于 Serv00 审批过渡期，待云端 SOCKS5 链式出口配置就绪后即可完全自愈。

无需开启频繁的心跳探测与节点竞速，长连接极其稳固，杜绝频繁切换导致的连接中断与 502 错误。

节点订阅更新与配置文件更新是两个独立设置。推荐使用本地测速固化的静态入口列表，并在小火箭中关闭频繁的自动订阅更新，避免由于入口 IP 频繁更换造成断连。

## Clash Verge Rev (Windows / macOS)

在 Clash Verge Rev（或 Mihomo 内核客户端）的「订阅」页面中导入 EdgeTunnel 订阅链接，并在「扩展配置 (Merge)」中引入 `clients/clash-verge.yaml`：

```
https://raw.githubusercontent.com/RealRayTan/cf-preferred-ips/main/clients/clash-verge.yaml
```

配置同样将分组对齐为 `日常流媒体` 与 `AI-专线`，节点由订阅中的 `CF-MEDIA` 自动提供，无需在客户端进行繁琐的手动配置。

参考：[分组及自动更新说明](https://github.com/LOWERTOP/Shadowrocket/wiki) · [分组配置语法](https://github.com/LOWERTOP/Shadowrocket/blob/main/lazy_group.conf)
