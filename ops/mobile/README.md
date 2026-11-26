# TuriMath Android app

A Capacitor shell around the chat in `ops/chat` (copied from TuriChips). The app holds no chat code: it opens
`https://turimath.<tailnet>.ts.net`, the VM's TuriMath chat served over Tailscale by its own tailnet machine, so web changes
go live without a new build. If the phone can't reach it (Tailscale off), it shows `www/offline.html`.

The URL is not in this repo (it's public): `configure.js` fills it into `capacitor.config.json` and `www/offline.html`
from `CHAT_URL` or a local, gitignored `.chat-url` file.

- **Phone:** install the Tailscale app, sign in to the same tailnet, then install the APK.
- **VM:** the `turimath` Tailscale node (`ops/tailscaled-turimath.service`) publishes the localhost-only chat to the tailnet over HTTPS.
  Nothing is exposed to the public internet.
- **Build** (needs JDK 21 and the Android SDK):
  ```
  npm install
  echo 'https://turimath.<tailnet>.ts.net' > .chat-url
  echo "sdk.dir=$HOME/Android/Sdk" > android/local.properties
  JAVA_HOME=~/.local/jdk-21 npm run apk
  ```
  The output is `android/app/build/outputs/apk/debug/app-debug.apk`.
- Install with `adb install -r <apk>` over USB, or copy the APK to the phone and open it.
- **Icons and splash** are generated from the Infinity Lotus logo (`ops/chat/static/brand/logo-1024.png`) on black.
