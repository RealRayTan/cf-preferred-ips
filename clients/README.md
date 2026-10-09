# 客户端配置

## 小火箭

`shadowrocket.conf` 基于使用者提供的懒人配置合并而成，包含原有服务分流、广告过滤和 CF 故障切换，不含节点认证信息。节点仍由原来的 EdgeTunnel 订阅提供；不要把它当成节点订阅导入。

在小火箭「配置」页添加以下地址，下载后选择「使用配置」，首页「全局路由」选择「配置」：

```
https://raw.githubusercontent.com/RealRayTan/cf-preferred-ips/main/clients/shadowrocket.conf
```

配置保留原有 DNS、Host、Google 重写与服务分流设置，把原来使用 `PROXY` 的规则改为 `CF-故障切换`。Steam 下载域名和 SteamCN 直连，Steam 其他服务仍按原规则代理。首次下载后选择「使用配置」，以后只使用这一份，不必在懒人配置与故障切换配置之间切换。

原文本没有广告拦截规则，本版补充 AdvertisingLite 广告域名集与规则集；域名拦截不需要安装解密证书，但不能保证清除 YouTube 视频等与内容共用域名的广告。原文本只指定 Google 中国域名的解密范围，本版保留该范围，没有新增证书或开启 HTTPS 解密。

Apple、WeChat、Global、China 改为原生 Shadowrocket 格式；Apple、Global、China 按规则作者说明同时引用 `_Domain.list`，避免遗漏拆分的域名规则。其余服务规则保留，没有仅因名称相似就删除。

配置的 `update-url` 已指向本仓库合并版，配置更新不会重新下载原懒人版本、丢失故障切换组。远程规则集仍来自各原作者并随其更新。配置源码保持精简，去掉了教学示例注释和空配置项。

分组通过正则匹配 `CF-01` 至 `CF-09`，也兼容迁移前的 `CF-01-Q71` 等评分名称。订阅更新后匹配当前节点，不需要逐个添加。若多个订阅中存在同名节点，进入「配置 → 配置文件 ⓘ → 代理分组 → CF-故障切换」，打开「订阅」开关，在「服务器节点」中限定为自己的 EdgeTunnel 订阅。

首次使用时打开该分组，确认包含订阅节点并测试。检测地址为 `https://www.gstatic.com/generate_204`，周期 300 秒，超时 8 秒；故障切换依赖最近一次自动检测，不保证某个网站始终可用或立即切换。

在「设置 → 订阅」开启「打开时更新」和「自动后台更新」，更新间隔可设为 6 小时；iOS「设置 → 通用 → 后台 App 刷新」允许小火箭。节点订阅更新与配置文件更新是两个独立设置。iOS 后台调度不能保证准点执行；强制结束应用后需要重新打开。

参考：[分组及自动更新说明](https://github.com/LOWERTOP/Shadowrocket/wiki) · [分组配置语法](https://github.com/LOWERTOP/Shadowrocket/blob/main/lazy_group.conf)
