# 小龙虾语音助手 - 远程部署指南
# 架构: Cloudflare Pages (前端) + Cloudflare Tunnel (本地后端)
#
# 前端: siri.agentsignals.ai → Cloudflare Pages
# 后端: api-siri.agentsignals.ai → Cloudflare Tunnel → 本地 FastAPI :3456
#
# ============================================================
# 第一步: 安装 Cloudflare CLI 工具
# ============================================================
# npm install -g wrangler
# winget install cloudflare.cloudflared   (Windows)
# brew install cloudflared                (Mac)

# ============================================================
# 第二步: 登录 Cloudflare
# ============================================================
# wrangler login
# cloudflared tunnel login

# ============================================================
# 第三步: 创建 Tunnel (只需一次)
# ============================================================
# cloudflared tunnel create crayfish-backend
# 记下 Tunnel ID，如: abc123-def456-...

# ============================================================
# 第四步: 配置 Tunnel DNS
# ============================================================
# cloudflared tunnel route dns crayfish-backend api-siri.agentsignals.ai

# ============================================================
# 第五步: 创建 tunnel 配置文件
# ============================================================
# 见本项目 cloudflared-config.yml 模板

# ============================================================
# 第六步: 部署前端到 Cloudflare Pages
# ============================================================
# 方式 A: CLI 部署 (手动)
#   1. 构建前端:
#        VITE_WS_URL=wss://api-siri.agentsignals.ai/ws npm run build
#   2. 部署到 Pages:
#        wrangler pages deploy dist --project-name=crayfish-voice

# 方式 B: GitHub 集成 (推荐)
#   1. 在 Cloudflare Dashboard → Pages → 新建项目 → 关联 GitHub 仓库
#   2. 构建设置:
#        Framework: None
#        Build command: npm run build
#        Build output: dist
#   3. 环境变量 (在 Pages 设置中添加):
#        VITE_WS_URL=wss://api-siri.agentsignals.ai/ws
#        VITE_ASR_ENGINE=volcano
#        VITE_VOLCANO_ASR_APP_ID=你的ID
#        VITE_VOLCANO_ASR_TOKEN=你的Token
#        VITE_VOLCANO_ASR_CLUSTER=volcengine_streaming_common
#        VITE_VAD_REDEMPTION_MS=1000

# ============================================================
# 第七步: 配置自定义域名
# ============================================================
# Cloudflare Dashboard → Pages → crayfish-voice → Custom domains
# 添加: siri.agentsignals.ai

# ============================================================
# 日常运行
# ============================================================
# 本地启动后端:
#   python3 backend/main.py
#
# 启动 tunnel (将本地后端暴露到公网):
#   cloudflared tunnel run crayfish-backend
#
# 手机访问:
#   https://siri.agentsignals.ai
