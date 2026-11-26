// Writes capacitor.config.json and www/offline.html from the templates, with the chat URL filled in.
// The URL (the VM's Tailscale name, port 8443) is kept out of this public repo: set CHAT_URL, or put it in .chat-url.
const fs = require("fs");
const url = (process.env.CHAT_URL || (fs.existsSync(".chat-url") && fs.readFileSync(".chat-url", "utf8")) || "").trim();
if (!/^https:\/\//.test(url)) {
  console.error("configure: set CHAT_URL=https://<vm tailnet name>:8443 (or write it to .chat-url)");
  process.exit(1);
}
for (const [src, dst] of [["capacitor.config.template.json", "capacitor.config.json"], ["offline.template.html", "www/offline.html"]])
  fs.writeFileSync(dst, fs.readFileSync(src, "utf8").replaceAll("__CHAT_URL__", url));
console.log("configure: app opens " + url);
