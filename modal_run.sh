cd ~/projects/CMU11-768_AIAgents/assignment1

# NOTE: WSL2 Usage -> Windows host proxy
WSL_PROXY_HOST="$(ip route show default | awk '/default/ {print $3; exit}')"
# TODO: Config your proxy port here
PORT=10808

export HTTP_PROXY="http://${WSL_PROXY_HOST}:${PORT}"
export HTTPS_PROXY="http://${WSL_PROXY_HOST}:${PORT}"
export ALL_PROXY="http://${WSL_PROXY_HOST}:${PORT}"
export NO_PROXY="localhost,127.0.0.1,::1,api.deepseek.com"

uv run modal setup