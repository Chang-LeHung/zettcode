# 桌面端与手机端

网页网关本来就能在手机上打开。两个客户端的打包方式不同：

- **桌面端**把网关自己的 Vue 页面装进 Electron 窗口，加上服务器列表，并把每个令牌放在平台的密钥库（如果有）。
- **安卓端**是一个 WebView 壳。它自己的小页面只列服务器地址；点开一个地址就加载该网关自己的页面，所以令牌在网关登录页输入，
  由页面的 cookie 保存。应用本身只存地址。

登录之后的一切——聊天、daemon、群组、Graph、日志、配置页——都是你熟悉的网关页面。

## 开始之前

启动一个带令牌的网关：

```sh
zettcode gateway start --host 0.0.0.0 --token "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
```

`start` 会打印地址和令牌。手机要能访问这个地址（用机器的局域网地址，不要用 `127.0.0.1`），并在防火墙里放行端口。
页面是明文 HTTP；离开可信网络时请放在 TLS 后面。

桌面端要求网关同版本，因为它从自己的 `app://` origin 调用 API。安卓壳直接加载网关自己的页面，因此旧网关也能用。

## 桌面端

在应用正式发布之前，从仓库构建：

```sh
make desktop                  # 类型检查、测试并构建窗口
cd clients/desktop && npm start
```

`make desktop-package` 还会为当前系统写出安装包（macOS 的 dmg/zip、Windows 的 NSIS、Linux 的 AppImage/deb），
放在 `clients/desktop/release/` 下。应用只有一个窗口，页面里的外部链接会用系统浏览器打开。

第一次打开时填写服务器的 **地址**、**令牌** 和可选的 **名称**；保存前会先测试令牌。**设置 → 服务器** 显示当前服务器，
**切换服务器** 回到列表。切换会重新加载页面，所以不会把一个网关的内容画在另一个网关旁边。

## 安卓端

构建需要 JDK 21 或更新版本，以及带 `compileSdk 36` 的 Android SDK：

```sh
make mobile                   # 检查配置并把 web/ 复制进 Android 工程
make mobile-apk               # 需要 ANDROID_HOME（或 android/local.properties）
```

APK 位于 `clients/mobile/android/app/build/outputs/apk/debug/`。装到手机上，打开 **ZettCode**。
`make package` 会同时构建这个 APK 和桌面安装包。

第一次打开只需要填网关的 **地址**，例如 `http://192.168.1.20:8765`；网关服务在地址的根路径下，所以带路径会被拒绝。
点一个服务器就会加载网关页面，页面会要求输入一次令牌并保存 cookie。列表只存地址，不存令牌；在网关页面按 Android 返回键会回到列表，
可以再打开另一个服务器。

图标和启动图由 `clients/mobile/assets/` 里的 ZettCode 标记生成；桌面端用 `clients/desktop/assets/icon.png`。
两份都来自网关的 `public/logo.svg`。

## 令牌保存在哪里

桌面端用 `safeStorage`（macOS Keychain、Windows DPAPI、Linux libsecret）加密服务器列表和令牌，并且只让所有者读文件。
平台没有真正的密钥库时（较老的 Linux 没有 secret service，或使用 `basic_text` 后端，它只有一个硬编码密钥），仍会写文件，
但权限只给所有者；在 Linux 上这个文件就是明文（`0600`）。

安卓端不会把令牌写进应用自己的存储。它把地址列表放在选择页的 `localStorage`；令牌在 WebView 里网关页面的登录 cookie 中，
应用重启后仍然有效（网关签发 30 天）。清除应用数据会删除地址并退出登录。Android 备份已关闭。

拿到令牌的人就能启动以你的身份执行命令的 agent。设备丢失时请更换令牌：
`zettcode gateway restart --token <新令牌>`，然后在你还在使用的每台设备上编辑服务器。离开自己的网络时优先用 HTTPS；
在明文 HTTP 的局域网里令牌会以明文经过网络。

## 限制

- 桌面端要和网关同版本；旧网关不认识它的 origin 和 WebSocket 令牌。安卓壳直接加载网关页面，没有这个限制。
- 桌面端在运行时会显示系统通知。安卓端目前还没有通知；它背后没有推送服务。
- 安卓壳里指向其他站点的链接会在同一个 WebView 中打开，没有地址栏；按 Android 返回键回到服务器列表。
- 暂时没有二维码或深链，地址（桌面端还有令牌）要手动输入或粘贴。
- 这个仓库不包含 iOS 应用。
