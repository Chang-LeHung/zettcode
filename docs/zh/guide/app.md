# 桌面端与手机端

网页网关本来就能在手机上打开。两个客户端的打包方式不同：

- **桌面端**（macOS、Windows、Linux）是带服务器列表的 Electron 窗口，打开一个服务器就加载该网关自己的页面。
- **安卓端**思路相同：它自己的小页面只列服务器地址，点开一个就加载该网关的页面。

两者的令牌都在网关登录页输入、由页面的 cookie 保存，应用本身只存地址。

登录之后的一切——聊天、daemon、群组、Graph、日志、配置页——都是你熟悉的网关页面。

## 开始之前

启动一个带令牌的网关：

```sh
zettcode gateway start --host 0.0.0.0 --token "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
```

`start` 会打印地址和令牌。手机要能访问这个地址（用机器的局域网地址，不要用 `127.0.0.1`），并在防火墙里放行端口。
页面是明文 HTTP；离开可信网络时请放在 TLS 后面。

桌面端和安卓端都是网关的一扇窗：选一个服务器就从网关加载它自己的页面，所以升级网关就会改变你看到的内容，应用本身很少需要更新。

## 桌面端

已为 macOS（Apple Silicon）、Windows 和 Linux 构建。安装包由 CI 在各自的系统上生成，目前还没有在真实的 Windows 或 Linux 机器上试过，
如果打不开请反馈。三个系统的安装包都挂在名为 `desktop-v<版本>` 的 GitHub release 上；它们没有签名，
所以 macOS 要用右键 → 打开，Windows SmartScreen 要点“更多信息 → 仍要运行”。也可以从仓库构建：

```sh
make desktop                  # 类型检查、测试并构建窗口
cd clients/desktop && npm start
```

`make desktop-package` 为当前系统写出安装包（macOS 的 dmg/zip、Windows 的 NSIS/zip、Linux 的 AppImage/deb/tar.gz），
放在 `clients/desktop/release/` 下。应用只有一个窗口，对话里的外部链接会用系统浏览器打开。

第一次打开时填写服务器的 **地址**；令牌在网关自己的登录页输入，窗口会保存那个 cookie。下次启动会重新打开上次的服务器。
**Server → Switch server…**（Ctrl/Cmd+Shift+S）回到列表；连不上的服务器也会回到列表并说明原因。

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

桌面端不保存令牌：和安卓端一样，它只写地址列表（和上次用的服务器），令牌在窗口里网关页面的登录 cookie 中，重启后仍然有效
（网关签发 30 天）。清除应用数据会删除地址并退出登录。

安卓端的地址列表放在选择页的 `localStorage`，cookie 在 WebView 里。Android 备份已关闭。

拿到令牌的人就能启动以你的身份执行命令的 agent。设备丢失时请更换令牌：
`zettcode gateway restart --token <新令牌>`，然后在你还在使用的每台设备上编辑服务器。离开自己的网络时优先用 HTTPS；
在明文 HTTP 的局域网里令牌会以明文经过网络。

## 限制

- 两个应用的壳都不要求特定的网关版本，但你看到的页面是网关的，想要新功能就运行较新的网关。
- 页面在窗口打开时会显示通知；两个应用背后都没有推送服务。
- 安卓壳里指向其他站点的链接会在同一个 WebView 中打开，没有地址栏；按 Android 返回键回到服务器列表。
- 暂时没有二维码或深链，地址要手动输入或粘贴。
- 这个仓库不包含 iOS 应用。
