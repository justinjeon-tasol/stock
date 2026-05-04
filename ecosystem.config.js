module.exports = {
  apps: [{
    name: "stock-agent",
    script: "/home/hyenbaejeon/stock/venv/bin/python",
    args: "main.py --mode schedule",
    cwd: "/home/hyenbaejeon/stock",
    autorestart: true,
    max_restarts: 10,
    restart_delay: 5000,
    max_memory_restart: "800M",
    log_file: "/home/hyenbaejeon/logs/stock-agent.log",
    error_file: "/home/hyenbaejeon/logs/stock-agent-error.log",
    log_date_format: "YYYY-MM-DD HH:mm:ss",
  }]
};
